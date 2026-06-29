# -*- coding: utf-8 -*-

# imports
from openerp.addons.web import http
from openerp.addons.web.controllers.main import content_disposition
from antipathy import Path
from urllib import urlopen
import logging
import re

_logger = logging.getLogger(__name__)
markem_base = Path('http://192.168.11.16:8000/')
markem_status = 'mkPngXfStatus.htm'

# work horses

class MarkemStatus(http.Controller):
    _cp_path = "/fis/markem"

    def _fix_url(self, matches):
        for t in matches.groups():
            if t.startswith(markem_base):
                t = t[len(markem_base):]
            # t = '"http://localhost:8069/fis/markem/status/%s"' % t
            t = '"/fis/markem/status/%s"' % t
            return t

    def _get_url(self, target):
        url = None
        try:
            url = urlopen(target)
            return url.info(), url.read()
        finally:
            if url is not None:
                url.close()

    @http.httprequest
    def status(self, request, **kw):
        _logger.debug('request path: %r', request.httprequest.path)
        target_path = markem_base / (request.httprequest.path[19:] or markem_status)
        _logger.debug('getting %r', target_path)
        info, data = self._get_url(target_path)
        _logger.debug('info: %r  %r', info.gettype(), info.getplist())
        if info.gettype() != 'text/html':
            return request.make_response(
                    data,
                    headers=[
                        ('Content-Disposition',  content_disposition(target_path.filename, request)),
                        ('Content-Type', info.gettype()),
                        ('Content-Length', len(data)),
                        ],
                    )
        data = re.sub('(?<=href=)("[^"]*"|.*?)(?=\s|>)', self._fix_url, data)
        data = re.sub('(?<=src=)("[^"]*"|.*?)(?=\s|>)', self._fix_url, data)
        return request.make_response(
                data,
                headers=[
                    ('Content-Type', 'text/html'),
                    ('Content-Length', len(data)),
                    ],
                )


