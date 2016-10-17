# -*- coding: utf-8 -*-
"""
Peony Clients

:class:`BasePeonyClient` only handles requests while
:class:`PeonyClient` adds some methods that could help when using
the Twitter APIs, with a method to upload a media
"""

import asyncio
import io
from contextlib import suppress

import aiohttp

from . import exceptions, general, oauth, utils
from .api import APIPath, StreamingAPIPath
from .commands import EventStreams, task
from .stream import StreamContext


class BasePeonyClient(oauth.Client):
    """
        Attributes/items become a :class:`api.APIPath` or
        :class:`api.StreamingAPIPath` automatically

    This class only handles the requests and makes accessing Twitter's
    APIs easy.

    Parameters
    ----------
    streaming_apis : iterable, optional
        Iterable containing the streaming APIs subdomains
    base_url : :obj:`str`, optional
        Format of the url for all the requests
    api_version : :obj:`str`, optional
        Default API version
    suffix : :obj:`str`, optional
        Default suffix of API endpoints
    loads : :obj:`function`, optional
        Function used to load JSON data
    error_handler : :obj:`function`, optional
        Requests decorator
    """

    def __init__(self, *args,
                 streaming_apis=None,
                 base_url=None,
                 api_version=None,
                 suffix='.json',
                 loads=utils.loads,
                 error_handler=utils.error_handler,
                 **kwargs):

        if streaming_apis is None:
            self.streaming_apis = general.streaming_apis
        else:
            self.streaming_apis = streaming_apis

        if base_url is None:
            self.base_url = general.twitter_base_api_url
        else:
            self.base_url = base_url

        if api_version is None:
            self.api_version = general.twitter_api_version
        else:
            self.api_version = api_version

        self._suffix = suffix

        self._loads = loads
        self.error_handler = error_handler

        super().__init__(*args, **kwargs)

        if callable(self.init_tasks):
            init_tasks = self.init_tasks()
        else:
            init_tasks = self.init_tasks

        if init_tasks is not None:
            with suppress(RuntimeError):
                # loop attribute was created in oauth.Client.__init__
                self.loop.run_until_complete(asyncio.wait(init_tasks))


    def init_tasks(self):
        """ tasks executed on initialization """
        pass

    def __getitem__(self, values):
        """
            Access the api you want

        This permits the use of any API you could know about

        For most api you only need to type

        >>> client[api]  # api is the api you want to access

        You can specify a custom api version using the syntax

        >>> client[api, version]  # version is the api version as a str

        For more complex requests

        >>> client[api, version, suffix, base_url]

        Returns
        -------
        api.BaseAPIPath
            To access an API endpoint
        """
        defaults = (None, self.api_version, self._suffix, self.base_url)
        keys = ['api', 'version', 'suffix', 'base_url']

        if isinstance(values, dict):
            # set values in the right order
            values = [values[key] for key in keys]
        elif isinstance(values, set):
            raise TypeError('Cannot use a set to access an api, '
                            'please use a dict, a tuple or a list instead')
        elif isinstance(values, str):
            values = [values, *defaults[1:]]
        elif values:
            if len(values) < len(keys):
                padding = (None,) * (len(keys) - len(values))
                values += padding

            values = [default if value is None else value
                      for value, default in zip(values, defaults)
                      if (value, default) != (None, None)]

        api, version, suffix, base_url = values

        base_url = base_url.format(api=api, version=version).rstrip('/')

        # use StreamingAPIPath if subdomain is in self.streaming_apis
        if api in self.streaming_apis:
            return StreamingAPIPath([base_url], suffix=suffix, client=self)
        else:
            return APIPath([base_url], suffix=suffix, client=self)

    def __getattr__(self, api):
        """
            Access the api you want

        Same as calling client[api]

        Returns
        -------
        api.BaseAPIPath
            To access an API endpoint
        """
        return self[api]

    async def request(self, method, url,
                      headers=None,
                      json=False,
                      **kwargs):
        """
            Make requests to the REST API

        Parameters
        ----------
        method : str
            Method to be used by the request
        url : str
            URL of the ressource
        headers : dict
            Custom headers (doesn't overwrite `Authorization` headers)
        json : bool
            Force json decoding

        Returns
        -------
        utils.PeonyResponse
            Response to the request
        """

        # prepare request arguments, particularly the headers
        req_kwargs = self.headers.prepare_request(
            method=method,
            url=url,
            headers=headers,
            **kwargs
        )

        async with aiohttp.ClientSession() as session:

            # make the request
            async with session.request(**req_kwargs) as response:
                if response.status // 100 == 2:
                    if json or url.endswith(".json") and json is not None:
                        # decode as json
                        content = await response.json(loads=self._loads)
                    else:
                        # decode as text
                        content = await response.text()

                    return utils.PeonyResponse(
                        response=content,
                        headers=response.headers,
                        url=response.url,
                        request=req_kwargs
                    )
                else:  # throw exceptions if status is not 2xx
                    await exceptions.throw(response)

    def stream_request(self, method, url, headers=None, *args, **kwargs):
        """
            Make requests to the Streaming API

        Parameters
        method : str
            Method to be used by the request
        url : str
            URL of the ressource
        headers : dict
            Custom headers (doesn't overwrite `Authorization` headers)

        Returns
        -------
        stream.StreamContext
            Stream context for the request
        """
        return StreamContext(
            method, url,
            *args,
            headers=headers,
            _headers=self.headers,
            _error_handler=self.error_handler,
            **kwargs
        )


class PeonyClient(BasePeonyClient):
    """
        A client with an easy handling of tasks

    You can create tasks by decorating a function from a child
    class with :class:`peony.task`

    You also attach a :class:`EventStream` to a subclass using
    the :func:`event_stream` of the subclass

    After creating an instance of the child class you will be able
    to run all the tasks easily by executing :func:`get_tasks`
    """

    def init_tasks(self):
        tasks = [self.__get_twitter_configuration()]
        if isinstance(self.headers, oauth.OAuth1Headers):
            tasks.append(self.__get_user())
        return tasks

    async def __get_twitter_configuration(self):
        """
        create a ``twitter_configuration`` attribute with the response
        of the endpoint
        https://api.twitter.com/1.1/help/configuration.json
        """
        api = self['api', general.twitter_api_version,
                   ".json", general.twitter_base_api_url]
        self.twitter_configuration = await api.help.configuration.get()

    async def __get_user(self):
        """
        create a ``user`` attribute with the response of the endpoint
        https://api.twitter.com/1.1/account/verify_credentials.json
        """
        api = self['api', general.twitter_api_version,
                   ".json", general.twitter_base_api_url]
        self.user = await api.account.verify_credentials.get()


    @classmethod
    def event_stream(cls, event_stream):
        """ Decorator to attach an event stream to the class """
        cls._streams = getattr(cls, '_streams', EventStreams())

        cls._streams.append(event_stream)
        return event_stream

    def get_tasks(self):
        """
            Get tasks attached to the instance

        Returns
        -------
        list
            List of tasks (:class:`asyncio.Task`)
        """
        funcs = [getattr(self, key) for key in dir(self)]
        tasks = [func(self) for func in funcs if isinstance(func, task)]

        if isinstance(self._streams, EventStreams):
            tasks.extend(self._streams.get_tasks(self))

        return tasks

    def get_task(self):
        """
        Returns
        -------
        asyncio.Task
            The only task of the instance
        """
        tasks = self.get_tasks()

        if len(tasks) == 1:
            return tasks[0]

        # raise an exception if there are more than one task
        elif self.tasks:
            raise RuntimeError("more than one task in %s" % self)

        # raise an exception if there are no tasks
        else:
            raise RuntimeError("no tasks in %s" % self)
