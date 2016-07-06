#!/usr/bin/env python
'''
brozzler/pywb.py - pywb support for rethinkdb index

Copyright (C) 2016 Internet Archive

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

try:
    import pywb.apps.cli
    import pywb.cdx.cdxdomainspecific
    import pywb.cdx.cdxobject
    import pywb.cdx.cdxserver
    import pywb.webapp.query_handler
except ImportError as e:
    logging.critical(
            '%s: %s\n\nYou might need to run "pip install '
            'brozzler[easy]".\nSee README.rst for more information.',
            type(e).__name__, e)
    sys.exit(1)
import sys
import logging
import rethinkstuff
import rethinkdb
import surt
import json

class RethinkCDXSource(pywb.cdx.cdxsource.CDXSource):
    def __init__(self, servers, db, table):
        self.servers = servers
        self.db = db
        self.table = table

    @property
    def r(self):
        try:
            return self._r
        except AttributeError:
            self._r = rethinkstuff.Rethinker(self.servers, self.db)
            return self._r

    def load_cdx(self, cdx_query):
        # logging.debug('vars(cdx_query)=%s', vars(cdx_query))
        rethink_results = self._query_rethinkdb(cdx_query)
        return self._gen_cdx_lines(rethink_results)

    def _gen_cdx_lines(self, rethink_results):
        for record in rethink_results:
            # XXX inefficient, it gets parsed later, figure out how to
            # short-circuit this step and create the CDXObject directly
            blob = {
                'url': record['url'],
                'mime': record['content_type'],
                'status': str(record['response_code']),
                'digest': record['sha1base32'],
                'length': str(record['length']), # XXX is this the right length?
                'offset': str(record['offset']),
                'filename': record['filename'],
            }
            # b'org,archive)/ 20160427215530 {"url": "https://archive.org/", "mime": "text/html", "status": "200", "digest": "VILUFXZD232SLUA6XROZQIMEVUPW6EIE", "length": "16001", "offset": "90144", "filename": "ARCHIVEIT-261-ONE_TIME-JOB209607-20160427215508135-00000.warc.gz"}'
            cdx_line = '{} {:%Y%m%d%H%M%S} {}'.format(
                    record['canon_surt'], record['timestamp'],
                    json.dumps(blob))
            yield cdx_line.encode('utf-8')

    def _query_rethinkdb(self, cdx_query):
        start_key = cdx_query.key.decode('utf-8')
        end_key = cdx_query.end_key.decode('utf-8')
        reql = self.r.table(self.table).between(
                [start_key[:150], rethinkdb.minval],
                [end_key[:150]+'!', rethinkdb.maxval],
                index='abbr_canon_surt_timestamp')
        reql = reql.order_by(index='abbr_canon_surt_timestamp')

        # filters have to come after order_by apparently

        # TODO support for POST, etc
        # http_method='WARCPROX_WRITE_RECORD' for screenshots, thumbnails
        reql = reql.filter(
                lambda capture: rethinkdb.expr(
                    ['WARCPROX_WRITE_RECORD','GET']).contains(
                        capture['http_method']))
        reql = reql.filter(
                lambda capture: (capture['canon_surt'] >= start_key)
                                 & (capture['canon_surt'] < end_key))

        if cdx_query.limit:
            reql = reql.limit(cdx_query.limit)

        logging.debug('rethinkdb query: %s', reql)
        results = reql.run()
        return results

class TheGoodUrlCanonicalizer(object):
    '''
    Replacement for pywb.utils.canonicalize.UrlCanonicalizer that produces
    surts with scheme and with trailing comma, and does not "massage"
    www.foo.org into foo.org.
    '''
    def __init__(self, surt_ordered=True):
        '''We are always surt ordered (surt_ordered param is ignored)'''
        self.surt_ordered = True

    def __call__(self, url):
        try:
            key = surt.surt(
                    url, trailing_comma=True, host_massage=False,
                    with_scheme=True)
            # logging.debug('%s -> %s', url, key)
            return key
        except Exception as e:
            raise pywb.utils.canonicalize.UrlCanonicalizeException(
                    'Invalid Url: ' + url)
