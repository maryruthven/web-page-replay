"""Installs certificate on phone with KitKat."""
import argparse
import logging
import os
import subprocess
import sys

KEYCODE_ENTER = '66'
KEYCODE_TAB = '61'


class AndroidCertInstaller(object):
  """Certificate installer for phones with KitKat."""

  def __init__(self, device_id, cert_name, cert_path):
    if not os.path.exists(cert_path):
      raise ValueError('Not a valid certificate path')
    self.device_id = device_id
    self.cert_name = cert_name
    self.cert_path = cert_path
    self.file_name = os.path.basename(self.cert_path)

  def _run_cmd(self, cmd):
    return subprocess.check_output(cmd)

  def _adb(self, *args):
    """Runs the adb command."""
    cmd = ['adb']
    if self.device_id:
      cmd.extend(['-s', self.device_id])
    cmd.extend(args)
    return self._run_cmd(cmd)

  def _adb_su_shell(self, *args):
    """Runs command as root."""
    cmd = ['shell', 'su', '-c']
    cmd.extend(args)
    return self._adb(*cmd)

  def _get_property(self, prop):
    return self._adb('shell', 'getprop', prop).strip()

  def check_device(self):
    install_warning = False
    if self._get_property('ro.product.device') != 'hammerhead':
      logging.warning('Device is not hammerhead')
      install_warning = True
    if self._get_property('ro.build.version.release') != '4.4.2':
      logging.warning('Version is not 4.4.2')
      install_warning = True
    if install_warning:
      logging.warning('Certificate may not install properly')

  def _input_key(self, key):
    """Inputs a keyevent."""
    self._adb('shell', 'input', 'keyevent', key)

  def _input_text(self, text):
    """Inputs text."""
    self._adb('shell', 'input', 'text', text)

  def _remove(self, file_name):
    """Deletes file."""
    if os.path.exists(file_name):
      os.remove(file_name)

  def _format_hashed_cert(self):
    """Makes a certificate file that follows the format of files in cacerts."""
    self._remove(self.reformatted_cert_path)
    contents = self._run_cmd(['openssl', 'x509', '-inform', 'PEM', '-text',
                              '-in', self.cert_path])
    description, begin_cert, cert_body = contents.rpartition('-----BEGIN '
                                                             'CERTIFICATE')
    contents = ''.join([begin_cert, cert_body, description])
    with open(self.reformatted_cert_path, 'w') as cert_file:
      cert_file.write(contents)

  def _remove_cert_from_cacerts(self):
    self._adb_su_shell('rm', self.android_cacerts_path)

  def _is_cert_installed(self):
    return (self._adb_su_shell('ls', self.android_cacerts_path).strip() ==
            self.android_cacerts_path)

  def install_cert(self, overwrite_cert=False):
    """Installs a certificate putting it in /system/etc/security/cacerts."""
    output = self._run_cmd(['openssl', 'x509', '-inform', 'PEM',
                            '-subject_hash_old', '-in', self.cert_path])
    self.reformatted_cert_path = output.partition('\n')[0].strip() + '.0'
    self.android_cacerts_path = ('/system/etc/security/cacerts/%s'
                                 % self.reformatted_cert_path)

    if self._is_cert_installed():
      if overwrite_cert:
        self._remove_cert_from_cacerts()
      else:
        logging.info('cert is already installed')
        return

    self._format_hashed_cert()
    self._adb('push', self.reformatted_cert_path, '/sdcard/')
    self._remove(self.reformatted_cert_path)
    self._adb_su_shell('mount', '-o', 'remount,rw', '/system')
    self._adb_su_shell(
        'sh', '-c', 'cat /sdcard/%s > /system/etc/security/cacerts/%s'
        % (self.reformatted_cert_path, self.reformatted_cert_path))
    self._adb_su_shell('chmod', '644', self.android_cacerts_path)
    if not self._is_cert_installed():
      logging.warning('Cert Install Failed')

  def install_cert_using_gui(self):
    """Installs certificate on the device using adb commands."""
    self.check_device()
    # TODO(mruthven): Add a check to see if the certificate is already installed
    # Install the certificate.
    logging.info('Installing %s on %s', self.cert_path, self.device_id)
    self._adb('push', self.cert_path, '/sdcard/')

    # Start credential install intent.
    self._adb('shell', 'am', 'start', '-W', '-a', 'android.credentials.INSTALL')

    # Move to and click search button.
    self._input_key(KEYCODE_TAB)
    self._input_key(KEYCODE_TAB)
    self._input_key(KEYCODE_ENTER)

    # Search for certificate and click it.
    # Search only works with lower case letters
    self._input_text(self.file_name.lower())
    self._input_key(KEYCODE_ENTER)

    # These coordinates work for hammerhead devices.
    self._adb('shell', 'input', 'tap', '300', '300')

    # Name the certificate and click enter.
    self._input_text(self.cert_name)
    self._input_key(KEYCODE_TAB)
    self._input_key(KEYCODE_TAB)
    self._input_key(KEYCODE_TAB)
    self._input_key(KEYCODE_ENTER)

    # Remove the file.
    self._adb('shell', 'rm', '/sdcard/' + self.file_name)


def parse_args():
  """Parses command line arguments."""
  parser = argparse.ArgumentParser(description='Install cert on device.')
  parser.add_argument(
      '-n', '--cert-name', default='dummycert', help='certificate name')
  parser.add_argument(
      '--overwrite', default=False, action='store_true',
      help='Overwrite certificate file if its already installed')
  parser.add_argument(
      '--device-id', help='device serial number')
  parser.add_argument(
      'cert_path', help='Certificate file path')
  return parser.parse_args()


def main():
  args = parse_args()
  cert_installer = AndroidCertInstaller(args.device_id, args.cert_name,
                                        args.cert_path)
  cert_installer.install_cert(args.overwrite)


if __name__ == '__main__':
  sys.exit(main())
