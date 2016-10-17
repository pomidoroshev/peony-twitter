# -*- coding: utf-8 -*-

import asyncio
import functools
import json
import sys
import traceback

import aiohttp

from . import exceptions

try:
    from magic import Magic
    mime = Magic(mime=True)
    magic = True
except:
    print('Could not load python-magic, fallback to mimetypes',
          file=sys.stderr)
    import mimetypes
    mime = mimetypes.MimeTypes()
    magic = False


class JSONObject(dict):
    """
        A dict in which you can access items as attributes

    >>> obj = JSONObject(key=True)
    >>> obj['key'] is obj.key
    True
    """

    def __getattr__(self, key):
        if key in self:
            return self[key]
        raise AttributeError("%s has no property named %s." %
                             (self.__class__.__name__, key))

    def __setattr__(self, *args):
        raise AttributeError("%s instances are read-only." %
                             self.__class__.__name__)
    __delattr__ = __setitem__ = __delitem__ = __setattr__


class PeonyResponse:
    """
        Response objects

    In these object you can access the headers, the request, the url
    and the response
    getting an attribute/item of this object will get the corresponding
    attribute/item of the response

    >>> peonyresponse.key is peonyresponse.response.key  # returns True
    >>>
    >>> # iterate over peonyresponse.response
    >>> for key in peonyresponse:
    ...     pass  # do whatever you want

    Parameters
    ----------
    response : dict or list
        Response object
    headers : dict
        Headers of the response
    url : str
        URL of the request
    request : dict
        Requests arguments
    """

    def __init__(self, response, headers, url, request):
        self.response = response
        self.headers = headers
        self.url = url
        self.request = request

    def __getattr__(self, key):
        """ get attributes from the response """
        return getattr(self.response, key)

    def __getitem__(self, key):
        """ get items from the response """
        return self.response[key]

    def __iter__(self):
        """ iterate over the response """
        return iter(self.response)

    def __str__(self):
        """ use the string of the response """
        return str(self.response)

    def __repr__(self):
        """ use the representation of the response """
        return repr(self.response)

    def __len__(self):
        """ get the lenght of the response """
        return len(self.response)


class handler_decorator:
    """
        A decorator for requests handlers

    implements the ``_error_handling`` argument

    Parameters
    ----------
    handler : function
        The error handler to decorate
    """

    def __init__(self, handler):
        functools.update_wrapper(self, handler)

    def __call__(self, request, error_handling=True):
        if error_handling:
            return self.__wrapped__(request)
        else:
            return request

    def __repr__(self):
        return repr(self.__wrapped__)


@handler_decorator
def error_handler(request):
    """
        The default error_handler

    The decorated request will retry infinitely on any handled error
    The exceptions handled are :class:`asyncio.TimeoutError` and
    :class:`exceptions.RateLimitExceeded`
    """

    @functools.wraps(request)
    async def decorated_request(timeout=10, **kwargs):
        while True:
            try:
                with aiohttp.Timeout(timeout):
                    return await request(**kwargs)

            except exceptions.RateLimitExceeded as e:
                traceback.print_exc(file=sys.stderr)
                delay = int(e.reset_in) + 1
                print("sleeping for %ds" % delay, file=sys.stderr)
                await asyncio.sleep(delay)

            except asyncio.TimeoutError:
                print("Request timed out, retrying", file=sys.stderr)

            except:
                raise

    return decorated_request


def get_args(func, skip=0):
    """
        Hackish way to get the arguments of a function

    Parameters
    ----------
    func : function
        Function to get the arguments from
    skip : :obj:`int`, optional
        Arguments to skip, defaults to 0 set it to 1 to skip the
        ``self`` argument of a method.

    Returns
    -------
    tuple
        Function's arguments
    """
    argcount = func.__code__.co_argcount
    return func.__code__.co_varnames[skip:argcount]


def print_error(msg=None, stderr=sys.stderr, error=None):
    """
        Print an exception and its traceback to stderr

    Parameters
    ----------
    msg : :obj:`str`, optional
        A message to add to the error
    stderr : file object
        A file object to write the errors to
    """
    output = [] if msg is None else [msg]
    output.append(traceback.format_exc().strip())

    print(*output, sep='\n', file=stderr)


def loads(json_data, *args, encoding="utf-8", **kwargs):
    """
        Custom loads function with an object_hook and automatic decoding

    Parameters
    ----------
    json_data : str
        The JSON data to decode
    *args
        Positional arguments, passed to :func:`json.loads`
    encoding : :obj:`str`, optional
        The encoding of the bytestring
    **kwargs
        Keyword arguments passed to :func:`json.loads`

    Returns
    -------
    :obj:`dict` or :obj:`list`
        Decoded json data
    """
    if isinstance(json_data, bytes):
        json_data = json_data.decode(encoding)

    return json.loads(json_data, *args, object_hook=JSONObject, **kwargs)
