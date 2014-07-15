"""Test routines to generate dummy certificates."""
import BaseHTTPServer
import os
import shutil
import ssl
import tempfile
import threading
import unittest

import certutils


class Server(BaseHTTPServer.HTTPServer):

  def __init__(self, https_root_ca_cert_path):
    BaseHTTPServer.HTTPServer.__init__(
        self, ('localhost', 0), BaseHTTPServer.BaseHTTPRequestHandler)
    self.socket = ssl.wrap_socket(
        self.socket, certfile=https_root_ca_cert_path, server_side=True,
        do_handshake_on_connect=False)

  def __enter__(self):
    thread = threading.Thread(target=self.serve_forever)
    thread.daemon = True
    thread.start()
    return self

  def cleanup(self):
    try:
      self.shutdown()
    except KeyboardInterrupt:
      pass

  def __exit__(self, type_, value_, traceback_):
    self.cleanup()


class CertutilsTest(unittest.TestCase):

  def _check_cert_file(self, cert_file_path, cert_str, key_str=None):
    cert_load = open(cert_file_path, 'r').read()
    if key_str:
      expected_cert = key_str + cert_str
    else:
      expected_cert = cert_str
    self.assertEqual(expected_cert, cert_load)

  def setUp(self):
    self._temp_dir = tempfile.mkdtemp(prefix='certutils_', dir='/tmp')

  def tearDown(self):
    if self._temp_dir:
      shutil.rmtree(self._temp_dir)

  def test_generate_dummy_ca_cert(self):
    subject = 'testSubject'
    c, _ = certutils.generate_dummy_ca_cert(subject)
    c = certutils.load_cert(c)
    self.assertEqual(c.get_subject().commonName, subject)

  def test_get_host_cert(self):
    ca_cert_path = os.path.join(self._temp_dir,'rootCA.pem')
    issuer = 'testCA'
    certutils.write_dummy_ca_cert(*certutils.generate_dummy_ca_cert(issuer),
                                  cert_path=ca_cert_path)

    with Server(ca_cert_path) as server:
      cert_str = certutils.get_host_cert('localhost', server.server_port)
      cert = certutils.load_cert(cert_str)
      self.assertEqual(issuer, cert.get_subject().commonName)

  def test_write_dummy_ca_cert(self):
    base_path = os.path.join(self._temp_dir, 'testCA')
    ca_cert_path = base_path + '.pem'
    cert_path = base_path + '-cert.pem'
    ca_cert_android = base_path + '-cert.cer'
    ca_cert_windows = base_path + '-cert.p12'

    self.assertFalse(os.path.exists(ca_cert_path))
    self.assertFalse(os.path.exists(cert_path))
    self.assertFalse(os.path.exists(ca_cert_android))
    self.assertFalse(os.path.exists(ca_cert_windows))
    c, k = certutils.generate_dummy_ca_cert()
    certutils.write_dummy_ca_cert(c, k, ca_cert_path)

    self._check_cert_file(ca_cert_path, c, k)
    self._check_cert_file(cert_path, c)
    self._check_cert_file(ca_cert_android, c)
    self.assertTrue(os.path.exists(ca_cert_windows))

  def test_generate_cert(self):
    ca_cert_path = os.path.join(self._temp_dir, 'testCA.pem')
    issuer = 'testIssuer'
    certutils.write_dummy_ca_cert(
        *certutils.generate_dummy_ca_cert(issuer), cert_path=ca_cert_path)

    with open(ca_cert_path, 'r') as root_file:
      root_string = root_file.read()
    subject = 'testSubject'
    cert_string = certutils.generate_cert(
        root_string, '', subject)
    cert = certutils.load_cert(cert_string)
    self.assertEqual(issuer, cert.get_issuer().commonName)
    self.assertEqual(subject, cert.get_subject().commonName)

    with open(ca_cert_path, 'r') as ca_cert_file:
      ca_cert_str = ca_cert_file.read()
    cert_string = certutils.generate_cert(ca_cert_str, cert_string,
                                          'host')
    cert = certutils.load_cert(cert_string)
    self.assertEqual(issuer, cert.get_issuer().commonName)
    self.assertEqual(subject, cert.get_subject().commonName)


if __name__ == '__main__':
  unittest.main()
