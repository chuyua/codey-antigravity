"""Exercise the release C ABI without invoking Cargo or a compiler."""
import argparse
import contextlib
import ctypes as c
import http.server
import json
import pathlib
import tempfile
import threading
import unittest


class Buffer(c.Structure):
    _fields_ = [('data', c.POINTER(c.c_ubyte)), ('len', c.c_size_t)]


Create = c.CFUNCTYPE(c.c_int32, c.c_void_p, c.c_size_t, c.POINTER(c.c_void_p), c.POINTER(Buffer))
Invoke = c.CFUNCTYPE(c.c_int32, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(Buffer))
Destroy = c.CFUNCTYPE(None, c.c_void_p)
Free = c.CFUNCTYPE(None, Buffer)


class Api(c.Structure):
    _fields_ = [('abi_version', c.c_uint32), ('struct_size', c.c_uint32),
                ('create', Create), ('invoke', Invoke), ('destroy', Destroy), ('free_buffer', Free)]


class Native:
    def __init__(self, api, instance):
        self.api, self.instance = api, instance

    def decode(self, buffer):
        try:
            return json.loads(c.string_at(buffer.data, buffer.len)) if buffer.len else None
        finally:
            self.api.free_buffer(buffer)

    def invoke(self, method, params=None, expected=0):
        raw = json.dumps({'method': method, 'params': params or {}}).encode()
        data, output = c.create_string_buffer(raw), Buffer()
        status = self.api.invoke(self.instance, data, len(raw), c.byref(output))
        value = self.decode(output)
        if expected == 0 and status != 0:
            raise RuntimeError(str(value))
        if expected != 0 and status == 0:
            raise AssertionError('Expected an ABI error, got success')
        return value


@contextlib.contextmanager
def native(config):
    with tempfile.TemporaryDirectory(prefix='codey-native-中文 space-') as temp:
        root = pathlib.Path(temp)
        for name in ['data', 'logs']:
            (root / name).mkdir()
        raw = json.dumps({'config': config, 'context': {
            'pluginId': 'dev.codey.antigravity-router', 'pluginDir': str(root),
            'dataDir': str(root / 'data'), 'logDir': str(root / 'logs'),
        }}, ensure_ascii=False).encode('utf-8')
        data, instance, output = c.create_string_buffer(raw), c.c_void_p(), Buffer()
        status = API.create(data, len(raw), c.byref(instance), c.byref(output))
        handle = Native(API, instance)
        value = handle.decode(output)
        if status != 0:
            if instance.value:
                raise AssertionError('Failed create returned a live instance')
            raise RuntimeError(str(value))
        if not instance.value:
            raise AssertionError('Successful create returned a null instance')
        try:
            yield handle
        finally:
            API.destroy(instance)


@contextlib.contextmanager
def catalog(body):
    state = {'body': body, 'status': 200, 'requests': []}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            state['requests'].append(self.path)
            data = json.dumps(state['body']).encode()
            self.send_response(state['status'])
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class ReleaseAbi(unittest.TestCase):
    def test_default_descriptor_and_disabled_claims(self):
        with native({'syncModels': False}) as plugin:
            descriptor = plugin.invoke('provider.describe')
            self.assertEqual(set(descriptor), {'name', 'baseUrl', 'upstreamProtocol', 'models', 'headers'})
            self.assertEqual(descriptor['upstreamProtocol'], 'openaiResponses')
            self.assertLessEqual(len(descriptor['models']), 32)
            ping = plugin.invoke('ping')
            self.assertFalse(ping['declareHostCapabilities'])
            self.assertFalse(ping['declareWebsockets'])
            self.assertEqual(plugin.invoke('request.beforeSend', {'metadata': {'routeId': 'other'}}),
                             {'action': 'continue'})
            plugin.invoke('unknown.method', expected=1)

    def test_capability_opt_in_is_separate_and_validated(self):
        with native({'syncModels': False, 'declareHostCapabilities': True}) as plugin:
            descriptor = plugin.invoke('provider.describe')
            for key in ['supportsRemoteCompaction', 'supportsNativeWebSearch', 'supportsWebsockets']:
                self.assertFalse(descriptor[key])
        with native({'syncModels': False, 'declareHostCapabilities': True, 'declareWebsockets': True}) as plugin:
            self.assertTrue(plugin.invoke('provider.describe')['supportsWebsockets'])

    def test_lifecycle_scoping_and_single_retry(self):
        for config, expected in [({'routeId': 'ours'}, 'abort'),
                                 ({'routeId': 'ours', 'retryOnce': True}, 'retry'),
                                 ({'routeId': 'ours', 'lifecycleEnabled': False}, 'continue')]:
            with native({'syncModels': False, **config}) as plugin:
                event = {'metadata': {'routeId': 'other'}, 'response': {'status': 429}, 'attempt': 0}
                self.assertEqual(plugin.invoke('request.afterHeaders', event)['action'], 'continue')
                event['metadata']['routeId'] = 'ours'
                self.assertEqual(plugin.invoke('request.afterHeaders', event)['action'], expected)
                event['attempt'] = 1
                self.assertNotEqual(plugin.invoke('request.afterHeaders', event)['action'], 'retry')
                plugin.invoke('request.completed')
                plugin.invoke('request.failed')
                plugin.invoke('request.cancelled')

    def test_unsafe_configurations_are_rejected(self):
        cases = [[], {'baseUrl': 'https://evil.test/v1'}, {'baseUrl': 'http://127.0.0.1:0/v1'},
                 {'baseUrl': 'http://127.0.0.1:08787/v1'}, {'models': []}, {'models': ['A', 'a']},
                 {'models': ['bad\nheader']}, {'models': [f'm{i}' for i in range(33)]},
                 {'retryOnce': True}, {'retryOnce': 2}, {'syncModels': 'true'}, {'secret': 'mock'},
                 {'enabled': True, 'lifecycleEnabled': False}, {'lifecycleEnabled': 'true'},
                 {'declareHostCapabilities': 'true'}, {'declareWebsockets': True}, {'routeId': '../x'}]
        for config in cases:
            with self.subTest(config=config), self.assertRaises(RuntimeError):
                with native(config):
                    pass

    def test_authenticated_cache_refresh_replaces_retired_models(self):
        with catalog({'data': [{'id': 'upstream-old'}]}) as (base, state):
            with native({'baseUrl': base, 'models': ['configured-retired']}) as plugin:
                self.assertEqual(plugin.invoke('provider.describe')['models'], ['upstream-old'])
                state['body'] = {'data': [{'id': 'upstream-new'}]}
                self.assertEqual(plugin.invoke('provider.describe')['models'], ['upstream-new'])
                state['status'] = 503
                self.assertEqual(plugin.invoke('provider.describe')['models'], ['upstream-new'])
                self.assertEqual(plugin.invoke('ping')['catalogSource'], 'proxy-cache')
            self.assertEqual(state['requests'], ['/v1/models?cached=1'] * 3)

    def test_initial_bad_catalog_never_publishes_stale_models(self):
        for body in [{'data': []}, {'data': [{'id': 'A'}, {'id': 'a'}]},
                     {'data': [{'id': f'm{i}'} for i in range(33)]},
                     {'data': [{'id': 'bad\nheader'}]}, {'error': 'unavailable'}]:
            with self.subTest(body=body), catalog(body) as (base, _):
                with native({'baseUrl': base, 'models': ['retired']}) as plugin:
                    error = plugin.invoke('provider.describe', expected=1)
                    self.assertIn('model catalog unavailable', str(error))
                    self.assertNotIn('models', error)

    def test_optional_real_budgets_preserve_unknown_window(self):
        with catalog({'data': [{'id': 'known', 'context_window': 524288, 'max_output_tokens': 12345},
                               {'id': 'unknown', 'max_output_tokens': 8192}]}) as (base, _):
            with native({'baseUrl': base, 'declareHostCapabilities': True}) as plugin:
                contexts = plugin.invoke('provider.describe')['modelContexts']
                self.assertEqual(contexts['known']['contextWindow'], 524288)
                self.assertEqual(contexts['known']['reserveOutputTokens'], 12345)
                self.assertNotIn('unknown', contexts)

    def test_repeated_create_destroy_and_owned_buffers(self):
        for _ in range(50):
            with native({'syncModels': False}) as plugin:
                for _ in range(5):
                    self.assertEqual(plugin.invoke('ping')['version'], '0.9.0')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=pathlib.Path, required=True)
    args = parser.parse_args()
    LIBRARY = c.CDLL(str(args.library.resolve()))
    entry = LIBRARY.codey_plugin_entry_v1
    entry.restype = c.POINTER(Api)
    entry.argtypes = []
    API = entry().contents
    if API.abi_version != 1 or API.struct_size != c.sizeof(Api):
        raise SystemExit('Release library ABI version/size mismatch')
    unittest.main(argv=['prebuilt-native-abi'], verbosity=2)
