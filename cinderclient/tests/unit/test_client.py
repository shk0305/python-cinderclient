# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import json

import fixtures
import mock

import cinderclient.client
import cinderclient.v1.client
import cinderclient.v2.client
from cinderclient import exceptions
from cinderclient.tests.unit import utils
from keystoneclient import adapter
from keystoneclient import exceptions as keystone_exception


class ClientTest(utils.TestCase):

    def test_get_client_class_v1(self):
        output = cinderclient.client.get_client_class('1')
        self.assertEqual(cinderclient.v1.client.Client, output)

    def test_get_client_class_v2(self):
        output = cinderclient.client.get_client_class('2')
        self.assertEqual(cinderclient.v2.client.Client, output)

    def test_get_client_class_unknown(self):
        self.assertRaises(cinderclient.exceptions.UnsupportedVersion,
                          cinderclient.client.get_client_class, '0')

    def test_log_req(self):
        self.logger = self.useFixture(
            fixtures.FakeLogger(
                format="%(message)s",
                level=logging.DEBUG,
                nuke_handlers=True
            )
        )

        kwargs = {
            'headers': {"X-Foo": "bar"},
            'data': ('{"auth": {"tenantName": "fakeService",'
                     ' "passwordCredentials": {"username": "fakeUser",'
                     ' "password": "fakePassword"}}}')
        }

        cs = cinderclient.client.HTTPClient("user", None, None,
                                            "http://127.0.0.1:5000")
        cs.http_log_debug = True
        cs.http_log_req('PUT', kwargs)

        output = self.logger.output.split('\n')

        self.assertNotIn("fakePassword", output[1])
        self.assertIn("fakeUser", output[1])

    def test_versions(self):
        v1_url = 'http://fakeurl/v1/tenants'
        v2_url = 'http://fakeurl/v2/tenants'
        unknown_url = 'http://fakeurl/v9/tenants'

        self.assertEqual('1',
                         cinderclient.client.get_volume_api_from_url(v1_url))
        self.assertEqual('2',
                         cinderclient.client.get_volume_api_from_url(v2_url))
        self.assertRaises(cinderclient.exceptions.UnsupportedVersion,
                          cinderclient.client.get_volume_api_from_url,
                          unknown_url)

    @mock.patch('cinderclient.client.SessionClient.get_endpoint')
    def test_get_base_url(self, mock_get_endpoint):
        url = 'http://192.168.122.104:8776/v3/de50d1f33a38415fadfd3e1dea28f4d3'
        mock_get_endpoint.return_value = url
        cs = cinderclient.client.SessionClient(self, api_version='3.0')
        self.assertEqual('http://192.168.122.104:8776/', cs._get_base_url())

    @mock.patch.object(cinderclient.client, '_log_request_id')
    @mock.patch.object(adapter.Adapter, 'request')
    @mock.patch.object(exceptions, 'from_response')
    def test_sessionclient_request_method(
            self, mock_from_resp, mock_request, mock_log):
        kwargs = {
            "body": {
                "volume": {
                    "status": "creating",
                    "imageRef": "username",
                    "attach_status": "detached"
                },
                "authenticated": "True"
            }
        }

        resp = {
            "text": {
                "volume": {
                    "status": "creating",
                    "id": "431253c0-e203-4da2-88df-60c756942aaf",
                    "size": 1
                }
            },
            "code": 202
        }

        mock_response = utils.TestResponse({
            "status_code": 202,
            "text": json.dumps(resp),
        })

        # 'request' method of Adaptor will return 202 response
        mock_request.return_value = mock_response
        session_client = cinderclient.client.SessionClient(session=mock.Mock())
        response, body = session_client.request(mock.sentinel.url,
                                                'POST', **kwargs)
        self.assertEqual(1, mock_log.call_count)

        # In this case, from_response method will not get called
        # because response status_code is < 400
        self.assertEqual(202, response.status_code)
        self.assertFalse(mock_from_resp.called)

    @mock.patch.object(cinderclient.client, '_log_request_id')
    @mock.patch.object(adapter.Adapter, 'request')
    def test_sessionclient_request_method_raises_badrequest(
            self, mock_request, mock_log):
        kwargs = {
            "body": {
                "volume": {
                    "status": "creating",
                    "imageRef": "username",
                    "attach_status": "detached"
                },
                "authenticated": "True"
            }
        }

        resp = {
            "badRequest": {
                "message": "Invalid image identifier or unable to access "
                           "requested image.",
                "code": 400
            }
        }

        mock_response = utils.TestResponse({
            "status_code": 400,
            "text": json.dumps(resp),
        })

        # 'request' method of Adaptor will return 400 response
        mock_request.return_value = mock_response
        session_client = cinderclient.client.SessionClient(
            session=mock.Mock())

        # 'from_response' method will raise BadRequest because
        # resp.status_code is 400
        self.assertRaises(exceptions.BadRequest, session_client.request,
                          mock.sentinel.url, 'POST', **kwargs)
        self.assertEqual(1, mock_log.call_count)

    @mock.patch.object(cinderclient.client, '_log_request_id')
    @mock.patch.object(adapter.Adapter, 'request')
    def test_sessionclient_request_method_raises_overlimit(
            self, mock_request, mock_log):
        resp = {
            "overLimitFault": {
                "message": "This request was rate-limited.",
                "code": 413
            }
        }

        mock_response = utils.TestResponse({
            "status_code": 413,
            "text": json.dumps(resp),
        })

        # 'request' method of Adaptor will return 413 response
        mock_request.return_value = mock_response
        session_client = cinderclient.client.SessionClient(
            session=mock.Mock())

        self.assertRaises(exceptions.OverLimit, session_client.request,
                          mock.sentinel.url, 'GET')
        self.assertEqual(1, mock_log.call_count)

    @mock.patch.object(exceptions, 'from_response')
    def test_keystone_request_raises_auth_failure_exception(
            self, mock_from_resp):

        kwargs = {
            "body": {
                "volume": {
                    "status": "creating",
                    "imageRef": "username",
                    "attach_status": "detached"
                },
                "authenticated": "True"
            }
        }

        with mock.patch.object(adapter.Adapter, 'request',
                               side_effect=
                               keystone_exception.AuthorizationFailure()):
            session_client = cinderclient.client.SessionClient(
                session=mock.Mock())
            self.assertRaises(keystone_exception.AuthorizationFailure,
                              session_client.request,
                              mock.sentinel.url, 'POST', **kwargs)

        # As keystonesession.request method will raise
        # AuthorizationFailure exception, check exceptions.from_response
        # is not getting called.
        self.assertFalse(mock_from_resp.called)


class ClientTestSensitiveInfo(utils.TestCase):
    def test_req_does_not_log_sensitive_info(self):
        self.logger = self.useFixture(
            fixtures.FakeLogger(
                format="%(message)s",
                level=logging.DEBUG,
                nuke_handlers=True
            )
        )

        secret_auth_token = "MY_SECRET_AUTH_TOKEN"
        kwargs = {
            'headers': {"X-Auth-Token": secret_auth_token},
            'data': ('{"auth": {"tenantName": "fakeService",'
                     ' "passwordCredentials": {"username": "fakeUser",'
                     ' "password": "fakePassword"}}}')
        }

        cs = cinderclient.client.HTTPClient("user", None, None,
                                            "http://127.0.0.1:5000")
        cs.http_log_debug = True
        cs.http_log_req('PUT', kwargs)

        output = self.logger.output.split('\n')
        self.assertNotIn(secret_auth_token, output[1])
