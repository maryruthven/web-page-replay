#!/usr/bin/env python
# Copyright 2012 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Retrieve web resources over http."""

import copy
import httplib
import logging
import random
import re
import StringIO

import httparchive
import platformsettings
import script_injector


# PIL isn't always available, but we still want to be able to run without
# the image scrambling functionality in this case.
try:
  import Image
except ImportError:
  Image = None

TIMER = platformsettings.timer


class HttpClientException(Exception):
  """Base class for all exceptions in httpclient."""
  pass


def _InjectScripts(response, inject_script):
  """Injects |inject_script| immediately after <head> or <html>.

  Copies |response| if it is modified.

  Args:
    response: an ArchivedHttpResponse
    inject_script: JavaScript string (e.g. "Math.random = function(){...}")
  Returns:
    an ArchivedHttpResponse
  """
  if type(response) == tuple:
    logging.warn('tuple response: %s', response)
  content_type = response.get_header('content-type')
  if content_type and content_type.startswith('text/html'):
    text = response.get_data_as_text()
    text, already_injected = script_injector.InjectScript(
        text, 'text/html', inject_script)
    if not already_injected:
      response = copy.deepcopy(response)
      response.set_data(text)
  return response


def _ScrambleImages(response):
  """If the |response| is an image, attempt to scramble it.

  Copies |response| if it is modified.

  Args:
    response: an ArchivedHttpResponse
  Returns:
    an ArchivedHttpResponse
  """

  assert Image, '--scramble_images requires the PIL module to be installed.'

  content_type = response.get_header('content-type')
  if content_type and content_type.startswith('image/'):
    try:
      image_data = response.response_data[0]
      image_data.decode(encoding='base64')
      im = Image.open(StringIO.StringIO(image_data))

      pixel_data = list(im.getdata())
      random.shuffle(pixel_data)

      scrambled_image = im.copy()
      scrambled_image.putdata(pixel_data)

      output_image_io = StringIO.StringIO()
      scrambled_image.save(output_image_io, im.format)
      output_image_data = output_image_io.getvalue()
      output_image_data.encode(encoding='base64')

      response = copy.deepcopy(response)
      response.set_data(output_image_data)
    except Exception:
      pass

  return response


class DetailedHTTPResponse(httplib.HTTPResponse):
  """Preserve details relevant to replaying responses.

  WARNING: This code uses attributes and methods of HTTPResponse
  that are not part of the public interface.
  """

  def read_chunks(self):
    """Return the response body content and timing data.

    The returned chunks have the chunk size and CRLFs stripped off.
    If the response was compressed, the returned data is still compressed.

    Returns:
      (chunks, delays)
        chunks:
          [response_body]                  # non-chunked responses
          [chunk_1, chunk_2, ...]          # chunked responses
        delays:
          [0]                              # non-chunked responses
          [chunk_1_first_byte_delay, ...]  # chunked responses

      The delay for the first body item should be recorded by the caller.
    """
    buf = []
    chunks = []
    delays = []
    if not self.chunked:
      chunks.append(self.read())
      delays.append(0)
    else:
      start = TIMER()
      try:
        while True:
          line = self.fp.readline()
          chunk_size = self._read_chunk_size(line)
          if chunk_size is None:
            raise httplib.IncompleteRead(''.join(chunks))
          if chunk_size == 0:
            break
          delays.append(TIMER() - start)
          chunks.append(self._safe_read(chunk_size))
          self._safe_read(2)  # skip the CRLF at the end of the chunk
          start = TIMER()

        # Ignore any trailers.
        while True:
          line = self.fp.readline()
          if not line or line == '\r\n':
            break
      finally:
        self.close()
    return chunks, delays

  @classmethod
  def _read_chunk_size(cls, line):
    chunk_extensions_pos = line.find(';')
    if chunk_extensions_pos != -1:
      line = line[:chunk_extention_pos]  # strip chunk-extensions
    try:
      chunk_size = int(line, 16)
    except ValueError:
      return None
    return chunk_size


class DetailedHTTPConnection(httplib.HTTPConnection):
  """Preserve details relevant to replaying connections."""
  response_class = DetailedHTTPResponse


class DetailedHTTPSResponse(DetailedHTTPResponse):
  """Preserve details relevant to replaying SSL responses."""
  pass


class DetailedHTTPSConnection(httplib.HTTPSConnection):
  """Preserve details relevant to replaying SSL connections."""
  response_class = DetailedHTTPSResponse


class RealHttpFetch(object):

  def __init__(self, real_dns_lookup):
    """Initialize RealHttpFetch.

    Args:
      real_dns_lookup: a function that resolves a host to an IP.
    """
    self._real_dns_lookup = real_dns_lookup

  @staticmethod
  def _GetHeaderNameValue(header):
    """Parse the header line and return a name/value tuple.

    Args:
      header: a string for a header such as "Content-Length: 314".
    Returns:
      A tuple (header_name, header_value) on success or None if the header
      is not in expected format. header_name is in lowercase.
    """
    i = header.find(':')
    if i > 0:
      return (header[:i].lower(), header[i+1:].strip())
    return None

  @staticmethod
  def _ToTuples(headers):
    """Parse headers and save them to a list of tuples.

    This method takes HttpResponse.msg.headers as input and convert it
    to a list of (header_name, header_value) tuples.
    HttpResponse.msg.headers is a list of strings where each string
    represents either a header or a continuation line of a header.
    1. a normal header consists of two parts which are separated by colon :
       "header_name:header_value..."
    2. a continuation line is a string starting with whitespace
       "[whitespace]continued_header_value..."
    If a header is not in good shape or an unexpected continuation line is
    seen, it will be ignored.

    Should avoid using response.getheaders() directly
    because response.getheaders() can't handle multiple headers
    with the same name properly. Instead, parse the
    response.msg.headers using this method to get all headers.

    Args:
      headers: an instance of HttpResponse.msg.headers.
    Returns:
      A list of tuples which looks like:
      [(header_name, header_value), (header_name2, header_value2)...]
    """
    all_headers = []
    for line in headers:
      if line[0] in '\t ':
        if not all_headers:
          logging.warning(
              'Unexpected response header continuation line [%s]', line)
          continue
        name, value = all_headers.pop()
        value += '\n ' + line.strip()
      else:
        name_value = RealHttpFetch._GetHeaderNameValue(line)
        if not name_value:
          logging.warning(
              'Response header in wrong format [%s]', line)
          continue
        name, value = name_value
      all_headers.append((name, value))
    return all_headers

  @staticmethod
  def _get_request_host_port(request):
    host_parts = request.host.split(':')
    host = host_parts[0]
    port = int(host_parts[1]) if len(host_parts) == 2 else None
    return host, port

  def _get_system_proxy(self, is_ssl):
    return platformsettings.get_system_proxy(is_ssl)

  def _get_connection(self, request_host, request_port, is_ssl):
    """Return a detailed connection object for host/port pair.

    If a system proxy is defined (see platformsettings.py), it will be used.

    Args:
      request_host: a host string (e.g. "www.example.com").
      request_port: a port integer (e.g. 8080) or None (for the default port).
      is_ssl: True if HTTPS connection is needed.
    Returns:
      A DetailedHTTPSConnection or DetailedHTTPConnection instance.
    """
    connection_host = request_host
    connection_port = request_port
    system_proxy = self._get_system_proxy(is_ssl)
    if system_proxy:
      connection_host = system_proxy.host
      connection_port = system_proxy.port

    # Use an IP address because WPR may override DNS settings.
    connection_ip = self._real_dns_lookup(connection_host)
    if not connection_ip:
      logging.critical('Unable to find host ip for name: %s', connection_host)
      return None

    if is_ssl:
      connection = DetailedHTTPSConnection(connection_ip, connection_port)
      if system_proxy:
        connection.set_tunnel(self, request_host, request_port)
    else:
      connection = DetailedHTTPConnection(connection_ip, connection_port)
    return connection

  def __call__(self, request):
    """Fetch an HTTP request.

    Args:
      request: an ArchivedHttpRequest
    Returns:
      an ArchivedHttpResponse
    """
    logging.debug('RealHttpFetch: %s %s', request.host, request.full_path)
    request_host, request_port = self._get_request_host_port(request)
    retries = 3
    while True:
      try:
        connection = self._get_connection(
            request_host, request_port, request.is_ssl)
        connect_start = TIMER()
        connection.connect()
        connect_delay = int((TIMER() - connect_start) * 1000)
        start = TIMER()
        connection.request(
            request.command,
            request.full_path,
            request.request_body,
            request.headers)
        response = connection.getresponse()
        headers_delay = int((TIMER() - start) * 1000)

        chunks, chunk_delays = response.read_chunks()
        delays = {
            'connect': connect_delay,
            'headers': headers_delay,
            'data': chunk_delays
            }
        archived_http_response = httparchive.ArchivedHttpResponse(
            response.version,
            response.status,
            response.reason,
            RealHttpFetch._ToTuples(response.msg.headers),
            chunks,
            delays)
        return archived_http_response
      except Exception, e:
        if retries:
          retries -= 1
          logging.warning('Retrying fetch %s: %s', request, e)
          continue
        logging.critical('Could not fetch %s: %s', request, e)
        return None


class RecordHttpArchiveFetch(object):
  """Make real HTTP fetches and save responses in the given HttpArchive."""

  def __init__(self, http_archive, real_dns_lookup, inject_script,
               cache_misses=None):
    """Initialize RecordHttpArchiveFetch.

    Args:
      http_archive: an instance of a HttpArchive
      real_dns_lookup: a function that resolves a host to an IP.
      inject_script: script string to inject in all pages
      cache_misses: instance of CacheMissArchive
    """
    self.http_archive = http_archive
    self.real_http_fetch = RealHttpFetch(real_dns_lookup)
    self.inject_script = inject_script
    self.cache_misses = cache_misses

  def __call__(self, request):
    """Fetch the request and return the response.

    Args:
      request: an ArchivedHttpRequest.
    Returns:
      an ArchivedHttpResponse
    """
    if self.cache_misses:
      self.cache_misses.record_request(
          request, is_record_mode=True, is_cache_miss=False)

    # If request is already in the archive, return the archived response.
    if request in self.http_archive:
      logging.debug('Repeated request found: %s', request)
      response = self.http_archive[request]
      mutate_response(request, response, self.callback_paths, self.ignore_paths)
    else:
      response = self.real_http_fetch(request)
      if response is None:
        return None
      self.http_archive[request] = response
    if self.inject_script:
      response = _InjectScripts(response, self.inject_script)
    logging.debug('Recorded: %s', request)
    return response


class ReplayHttpArchiveFetch(object):
  """Serve responses from the given HttpArchive."""

  def __init__(self, http_archive, real_dns_lookup, inject_script,
               use_diff_on_unknown_requests=False, cache_misses=None,
               use_closest_match=False, scramble_images=False):
    """Initialize ReplayHttpArchiveFetch.

    Args:
      http_archive: an instance of a HttpArchive
      real_dns_lookup: a function that resolves a host to an IP.
      inject_script: script string to inject in all pages
      use_diff_on_unknown_requests: If True, log unknown requests
        with a diff to requests that look similar.
      cache_misses: Instance of CacheMissArchive.
        Callback updates archive on cache misses
      use_closest_match: If True, on replay mode, serve the closest match
        in the archive instead of giving a 404.
    """
    self.http_archive = http_archive
    self.inject_script = inject_script
    self.use_diff_on_unknown_requests = use_diff_on_unknown_requests
    self.cache_misses = cache_misses
    self.use_closest_match = use_closest_match
    self.scramble_images = scramble_images
    self.real_http_fetch = RealHttpFetch(real_dns_lookup)

  def __call__(self, request):
    """Fetch the request and return the response.

    Args:
      request: an instance of an ArchivedHttpRequest.
    Returns:
      Instance of ArchivedHttpResponse (if found) or None
    """
    if request.host.startswith('127.0.0.1:'):
      return self.real_http_fetch(request)

    response = self.http_archive.get(request)
    mutate_response(request, response, self.callback_paths, self.ignore_paths)

    if self.use_closest_match and not response:
      closest_request = self.http_archive.find_closest_request(
          request, use_path=True)
      if closest_request:
        response = self.http_archive.get(closest_request)
        if response:
          logging.info('Request not found: %s\nUsing closest match: %s',
                       request, closest_request)

    if self.cache_misses:
      self.cache_misses.record_request(
          request, is_record_mode=False, is_cache_miss=not response)

    if not response:
      reason = str(request)
      if self.use_diff_on_unknown_requests:
        diff = self.http_archive.diff(request)
        if diff:
          reason += (
              "\nNearest request diff "
              "('-' for archived request, '+' for current request):\n%s" % diff)
      logging.warning('Could not replay: %s', reason)
    else:
      if self.inject_script:
        response = _InjectScripts(response, self.inject_script)
      if self.scramble_images:
        response = _ScrambleImages(response)
    return response

def mutate_response(request, response, callback_paths, ignore_paths):
  for callback_path in callback_paths:
    if re.match(r'%s' % callback_path, '%s%s' % (request.host, request.full_path)):
      logging.info('doing callback replacement')
      logging.info(request.full_path)

      newkey = request.full_path.rsplit('callback=_xdc_._', 1)[1]
      logging.error(newkey)
      resp_text = response.get_response_as_text()
      logging.error('text %s', resp_text)
      oldkey = re.search('_xdc_._(.{9})', resp_text).group(1)
      logging.info("oldkey = %s", oldkey)
      new_resp_text = resp_text.replace(oldkey, newkey)
      logging.info('new_resp_text: %s', new_resp_text)
      response.set_response_from_text(new_resp_text)

  if request.path in ignore_paths:
    logging.info('matched! %s', request.path)
    resp_text = response.get_response_as_text()
    logging.info('len resp = %d', len(resp_text))
    query_parts = request.full_path.split('&')

    ech_part = None
    psi_part = None
    for part in query_parts:
      if part.startswith('ech='):
        ech_part = part
      elif part.startswith('psi='):
        psi_part = part

    logging.info('ech_part = %s', ech_part)
    logging.info('psi_part = %s', psi_part)

    old_ech_stuff = re.search('ech=\d+', resp_text).group(0)
    logging.info('old_ech_stuff = %s', old_ech_stuff)

    old_psi_stuff = re.search('psi=[A-Za-z0-9_\.]+', resp_text).group(0)
    logging.info('old_psi_stuff = %s', old_psi_stuff)

    replaced1 = resp_text.replace(old_ech_stuff, ech_part)
    replaced2 = replaced1.replace(old_psi_stuff, psi_part)
    logging.info('len resp2 = %d', len(replaced2))
    response.set_response_from_text(replaced2)

class ControllableHttpArchiveFetch(object):
  """Controllable fetch function that can swap between record and replay."""

  def __init__(self, http_archive, real_dns_lookup,
               inject_script, use_diff_on_unknown_requests,
               use_record_mode, rules, cache_misses, use_closest_match,
               scramble_images):
    """Initialize HttpArchiveFetch.

    Args:
      http_archive: an instance of a HttpArchive
      real_dns_lookup: a function that resolves a host to an IP.
      inject_script: script string to inject in all pages.
      use_diff_on_unknown_requests: If True, log unknown requests
        with a diff to requests that look similar.
      use_record_mode: If True, start in server in record mode.
      cache_misses: Instance of CacheMissArchive.
      use_closest_match: If True, on replay mode, serve the closest match
        in the archive instead of giving a 404.
    """
    self.http_archive = http_archive
    self.record_fetch = RecordHttpArchiveFetch(
        http_archive, real_dns_lookup, inject_script,
        cache_misses)
    self.replay_fetch = ReplayHttpArchiveFetch(
        http_archive, real_dns_lookup, inject_script,
        use_diff_on_unknown_requests, cache_misses,
        use_closest_match, scramble_images)
    if use_record_mode:
      self.SetRecordMode()
    else:
      self.SetReplayMode()
    self.parse_rules(rules)

  def parse_rules(self, rules):
    ignore_paths = set()
    callback_paths = set()

    for rule, paths, action, values in rules:
      if rule == "isFetchPath":
        if action == "replaceCallback":
          for value in values:
            callback_paths.add('%s%s' % (paths, value))
            logging.error(callback_paths)
        elif action == "ignorePath":
          ignore_paths.update(paths)

    self.replay_fetch.callback_paths = callback_paths
    self.replay_fetch.ignore_paths = ignore_paths
    self.record_fetch.callback_paths = callback_paths
    self.record_fetch.ignore_paths = ignore_paths

  def SetRecordMode(self):
    self.fetch = self.record_fetch
    self.is_record_mode = True

  def SetReplayMode(self):
    self.fetch = self.replay_fetch
    self.is_record_mode = False

  def __call__(self, *args, **kwargs):
    """Forward calls to Replay/Record fetch functions depending on mode."""
    return self.fetch(*args, **kwargs)
