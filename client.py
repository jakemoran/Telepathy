import json

from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError


class MalformedResponse(Exception):
    pass


class RequestError(Exception):
    pass


def _get_upload_args(**kwargs):
    args = {}
    for key, default, typ in [('allow_commercial_use', 'd', str),
                              ('allow_modifications', 'd', str),
                              ('publicly_visible', 'y', str),
                              ('scale_units', None, str),
                              ('scale_type', None, str),
                              ('scale_lower', None, float),
                              ('scale_upper', None, float),
                              ('scale_est', None, float),
                              ('scale_err', None, float),
                              ('center_ra', None, float),
                              ('center_dec', None, float),
                              ('parity', None, int),
                              ('radius', None, float),
                              ('downsample_factor', None, int),
                              ('positional_error', None, float),
                              ('tweak_order', None, int),
                              ('crpix_center', None, bool),
                              ('invert', None, bool),
                              ('image_width', None, int),
                              ('image_height', None, int),
                              ('x', None, list),
                              ('y', None, list),
                              ('album', None, str),
                              ]:
        if key in kwargs:
            val = kwargs.pop(key)
            val = typ(val)
            args.update({key: val})
        elif default is not None:
            args.update({key: default})
    print('Upload args:', args)
    return args


class Client(object):
    default_url = 'http://nova.astrometry.net/api/'

    def __init__(self, apiurl=default_url):
        self.session = None
        self.apiurl = apiurl

    def get_url(self, service):
        return self.apiurl + service

    def send_request(self, service, args=None, file_args=None):

        if args is None:
            args = {}

        if self.session is not None:
            args.update({'session': self.session})

        print('Python:', args)
        args_json = json.dumps(args)
        print('Sending json:', args_json)
        url = self.get_url(service)
        print('Sending to URL:', url)

        if file_args is not None:
            import random
            boundary_key = ''.join([random.choice('0123456789') for i in range(19)])
            boundary = '===============%s==' % boundary_key
            headers = {'Content-Type':
                           'multipart/form-data; boundary="%s"' % boundary}
            data_pre = (
                    '--' + boundary + '\n' +
                    'Content-Type: text/plain\r\n' +
                    'MIME-Version: 1.0\r\n' +
                    'Content-disposition: form-data; name="request-json"\r\n' +
                    '\r\n' +
                    args_json + '\n' +
                    '--' + boundary + '\n' +
                    'Content-Type: application/octet-stream\r\n' +
                    'MIME-Version: 1.0\r\n' +
                    'Content-disposition: form-data; name="file"; filename="%s"' % file_args[0] +
                    '\r\n' + '\r\n')
            data_post = (
                    '\n' + '--' + boundary + '--\n')
            data = data_pre.encode() + file_args[1] + data_post.encode()

        else:
            # Else send x-www-form-encoded
            data = {'request-json': args_json}
            print('Sending form data:', data)
            data = urlencode(data)
            data = data.encode('utf-8')
            print('Sending data:', data)
            headers = {}

        request = Request(url=url, headers=headers, data=data)

        try:
            f = urlopen(request)
            txt = f.read()
            print('Got json:', txt)
            result = json.loads(txt)
            print('Got result:', result)
            stat = result.get('status')
            print('Got status:', stat)
            if stat == 'error':
                errstr = result.get('errormessage', '(none)')
                raise RequestError('server error message: ' + errstr)
            return result
        except HTTPError as e:
            print('HTTPError', e)
            txt = e.read()
            open('err.html', 'wb').write(txt)
            print('Wrote error text to err.html')

    def login(self, apikey):
        args = {'apikey': apikey}
        result = self.send_request('login', args)
        sess = result.get('session')
        print('Got session:', sess)
        if not sess:
            raise RequestError('no session in result')
        self.session = sess

    def upload(self, fn=None, **kwargs):
        args = _get_upload_args(**kwargs)
        file_args = None

        if fn is not None:
            try:
                f = open(fn, 'rb')
                file_args = (fn, f.read())
            except IOError:
                print('File %s does not exist' % fn)
                raise

        return self.send_request('upload', args, file_args)
