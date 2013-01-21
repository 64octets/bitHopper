"""
Stub for networking module
"""

import logging, traceback, json, base64
import bitHopper.Logic
import bitHopper.LaggingLogic
import bitHopper.Tracking as Tracking
from bitHopper.util import rpc_error
import btcnet_info
import socket
import gevent
import requests, requests.exceptions
from copy import deepcopy

try:
    config = {'pool_maxsize':1000}
    session = requests.session(config=config)
except TypeError:
    # Fix broken behavior in requests.
    # See https://github.com/kennethreitz/requests/issues/1104
    import requests.adapters
    session = requests.Session()
    session.mount('http://', requests.adapters.HTTPAdapter(pool_connections=1000, pool_maxsize=1000))
    session.mount('https://', requests.adapters.HTTPAdapter(pool_connections=1000, pool_maxsize=1000))

i = 0

def request( url, body = '', headers = {}, method='POST', timeout = 30):
    """
    Generic network wrapper function
    """

    #traceback.print_stack()

    r = session.request(method, url=url, data=body, headers=headers, timeout=timeout, verify=False)
    return r.content, r.headers

def get_lp(url, username, password, server):
    """
    Gets a lp
    """
    headers = {}
    headers['Authorization'] = "Basic " +base64.b64encode(username+ ":" + password).replace('\n','')

    if 'http' not in url:
        url = "http://" + url

    r = session.request('GET', url, headers=headers, timeout=30*60, prefetch=True, verify=False)

    gevent.spawn(Tracking.add_work_unit, r.content, server, username, password)

    return r.content, r.headers


def send_work( url, worker, password, headers={}, body=[], timeout = 30, method='POST'):
    """
    Does preproccesing and header setup for sending a work unit
    """
    if not url:
        return None, None

    body = json.dumps(body, ensure_ascii = True)
    headers['Authorization'] = "Basic " +base64.b64encode(worker+ ":" + password).replace('\n','')
    headers['Content-Type'] = 'application/json'
    if 'http' not in url:
        url = 'http://' + url

    return request(url, body = body, headers= headers, method=method, timeout = timeout)

def get_work( headers = {}):
    """
    Gets a work item
    """
    while True:
        server, username, password = bitHopper.Logic.get_server()
        url = btcnet_info.get_pool(server)
        if not url:
            bitHopper.LaggingLogic.lag(server, username, password)
            continue

        url = url['mine.address']
        request = {'params':[], 'id':1, 'method':'getwork'}

        try:
            content, server_headers = send_work( url, username, password, headers, request, timeout=1)
        except (socket.error, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            content, server_headers = None, None
        except:
            logging.error(traceback.format_exc())
            content, server_headers = None, None

        if not content:
            bitHopper.LaggingLogic.lag(server, username, password)
            continue

        gevent.spawn(Tracking.add_work_unit, content, server, username, password)
        gevent.spawn(Tracking.headers, server_headers, server)

        return content, deepcopy(server_headers)

def send_work_lp(url, username, password, server):
    _, server_headers = send_work(url, username, password)
    gevent.spawn(Tracking.headers, server_headers, server)

def submit_work(rpc_request, headers = {}):
    """
    Submits a work item
    """
    server, username, password = bitHopper.Tracking.get_work_unit(rpc_request)

    if not server:
        return rpc_error('Merkle Root Expired'), {}

    url = btcnet_info.get_pool(server)['mine.address']
    if not url:
        logging.error('NO URL FOR %s', server)
        return rpc_error('No Url for pool'), {}

    content, server_headers = bitHopper.Network.send_work(url, username, password, headers = headers, body = rpc_request)

    gevent.spawn(Tracking.add_result, content, server, username, password)
    gevent.spawn(Tracking.headers, server_headers, server)

    return content, deepcopy(server_headers)

