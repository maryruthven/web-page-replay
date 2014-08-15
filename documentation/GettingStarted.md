# Prerequisites
* A Mac running OS X 10.6 ("Snow Leopard") or Linux (tested with Ubuntu
Lucid). Support for Windows is still experimental
* [Python 2.6](http://www.python.org/download/releases/2.6.6/)

# Install
Only do this the first time.

1. Open the Terminal application and download the source.
```
$ git clone https://github.com/chromium/web-page-replay.git
```
2. Move to the newly created directory.
```
$ cd web-page-replay
```
## Linux-specific install steps
On Linux, Dummynet must be installed to simulate network conditions.

1. For the Linux code, try downloading the [latest linux sources from Marta
Carbone](http://info.iet.unipi.it/~marta/dummynet/). These are more up-to-date than what is found on the [Dummynet
homepage](http://info.iet.unipi.it/~luigi/dummynet/).
2. Build and install:
```
$ tar -C /tmp -xvzf ipfw3-20120119.tgz
$ cd /tmp/ipfw3-20120119
$ make
[Ignore output like the following:]
        echo "  ERROR: Kernel configuration is invalid.";\
        echo "         include/generated/autoconf.h or
include/config/auto.conf are missing.";\
        echo "         Run 'make oldconfig && make prepare' on kernel
src to fix it.";\
[The lines will print without "echo" if there is an actual error.]
$ sudo insmod dummynet2/ipfw_mod.ko
$ sudo cp ipfw/ipfw /usr/local/sbin
```
3. To remove it later
```
$ sudo rmmod ipfw_mod.ko
```
## Windows-specific install steps
*Windows support is experimental and not well tested.* On Windows XP, the
Dummynet driver must be installed to simulate network conditions
(Drivers for Windows Vista and Windows 7 are currently unavailable).

1. Control Panel -> Network Connections -> Right-click adapter in use ->
select Properties
2. Click Install... -> Service -> Add... -> Have Disk...
3. Browse... ->
web-page-replay-read-only\third_party\ipfw_win32\netipfw.inf
4. Click Open -> Ok -> Ok
  - Accept any warnings for installing an unknown driver

# Record
First you must record the web page or pages that you wish to replay.

1. Open the web browser you wish to use and clear its cache so that all
resources will be requested from the network.
2. Switch to the Terminal application and start the program in record mode.
All HTTP requests performed on the machine while it is running will be
saved into the archive.
```
$ sudo ./replay.py --record ~/archive.wpr
```
3. Load the web page or pages in the open web browser. Be sure to wait
until each is fully loaded.
4. Stop recording by killing the replay.py process with Ctrl+c. The archive
will be saved to ~/archive.wpr.

# Replay
After you have created an archive, you may later replay it at any time.

1. Start the program in replay mode with a previously recorded archive.
```
$ sudo ./replay.py ~/archive.wpr
```
2. Load recorded pages in a web browser. A 404 will be served for any pages
or resources not in the recorded archive.
3. Stop replaying by killing the replay.py process with Ctrl+c.

## Network simulation examples
During replay, you may simulate desired network conditions. This is
useful for benchmarking.

* 128KByte/s uplink bandwidth, 4Mbps/s downlink bandwidth with 100ms RTT
time
```
$ sudo ./replay.py --up 128KByte/s --down 4Mbit/s --delay_ms=100 archive.wpr
```
* 1% packet loss rate
```
$ sudo ./replay.py --packet_loss_rate=0.01 ~/archive.wpr
```

## Using browser proxy settings
You may choose to disable the forwarding of DNS requests to the local
replay server. If DNS request forwarding is disabled, an external
mechanism must be used to forward traffic to the replay server.

* Disable DNS forwarding
```
$ ./replay.py --no-dns_forwarding --record ~/archive.wpr
```
* Forwarding traffic to replay server (via Google Chrome on linux)
1. Go to Chrome Preferences -> Under the Hood -> Change Proxy Settings
2. Under Manual Proxy configuration -> HTTP proxy, enter 127.0.0.1 for IP
and the port that web page replay is configured to listen to (default
80).

Alternatively, traffic forwarding may also be configured via command
line flags.
```
$ google-chrome --host-resolver-rules="MAP * 127.0.0.1:80,EXCLUDE localhost"
```

# HTTPS/SSL support
HTTPS is enabled by default. To disable HTTPS run replay.py with "--no-ssl".

## Ignore Certificate Errors

By default, Web Page Replay, creates a self-signed certificate to serve
SSL traffic. In order for it to work, browsers need to be configured to
ignore certificate errors. Be aware that doing so opens a giant security
hole.

```
$ google-chrome --ignore-certificate-errors
```

Firefox has [a configuration file for
exceptions](https://developer.mozilla.org/En/Cert_override.txt). That requires listing
each host that gets used. If you have a better solution, please add it
to the comments below. IE and Safari options are also needed.

## Dynamic Certificate Generation

Web Page Replay can dynamically generate certificates from a root CA certificate.
If the device has the root CA public key installed as a trusted CA then the browser
will trust those certificates and believe replay is the correct host. This allows
the browser to behave normally unlike just ignoring the certificate errors.

When sslproxy gets a connection it queries the appropriate host and gets the correct
SNI from the returned certificate. It then creates a certificate with that server
name and communicates with the client using that generated certificate. The
certificate is saved in the archive and can be looked up later if there are any
future requests with the same host.

![Alt sslproxy](SslProxyDiagram.png "sslproxy")

Dynamic certificate generation requires that you supply replay with a root
CA certificate. Use certutils.py to generate the dummy CA and pass the filename to
replay on creation.

```
$ ./replay.py --should-generate-certs --https_ca_cert_path='rootCA.pem'
```

The public key of the root certificate will need to be installed on the device being
used in the test. Use adb_install_cert to install the certificate on Android devices.

```
$ ./adb_install_cert.py 'rootCA.crt'
```

One way to install the public key on iOS is to serve the certificate then visit that
page with a ".crt" extension. A dialog to install the certificate will pop up then
click install.

# Troubleshooting

## Permission errors

On Linux, either of the following two errors are permission problems:

```
python: can't open file './replay.py': [Errno 13] Permission denied
```
```
Traceback (most recent call last):
  File "./replay.py", line 50, in <module>
    import dnsproxy
  File "/home/slamm/p/wpr/dnsproxy.py", line 19, in <module>
    import platformsettings
ImportError: No module named platformsettings
```
This can happen if you checkout the files to an NFS directory. Either
move the files to a local directory, or make them world
readable/executable.

## Unable to access auto mounted directories
WPR can cause autofs to hang. On Ubuntu, the following command fixes it:

```
$ sudo restart autofs
```

# Help

For full usage instructions and advanced options, see the program's
help.

```
$ ./replay.py --help
```
