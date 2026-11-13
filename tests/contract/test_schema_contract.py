import unittest
from unittest.mock import patch
from graphql import build_schema
import os
from check_live_schema import access_token, validate_operations


class ContractTests(unittest.TestCase):
    def test_rejects_unknown_field_and_wrong_variable_type(self):
        schema = build_schema('type Query { missions(limit: Int): String }')
        with patch('check_live_schema.operations') as operations:
            operations.QUERY_BAD = 'query Bad($limit: String) { missions(limit: $limit) nextToken }'
            errors = validate_operations(schema)
        self.assertTrue(any('nextToken' in error for error in errors))
        self.assertTrue(any('Int' in error and 'String' in error for error in errors))

    def test_valid_operation(self):
        schema = build_schema('type Query { missions(limit: Int): String }')
        with patch('check_live_schema.operations') as operations:
            operations.QUERY_GOOD = 'query Good($limit: Int) { missions(limit: $limit) }'
            self.assertEqual(validate_operations(schema), [])

    def test_refresh_token_mints_a_fresh_access_token(self):
        calls = []

        def fake_request(endpoint, api_key, query, variables=None, bearer_token=None, opener=None):
            calls.append((query, variables, bearer_token))
            return {'auth_refreshToken': {'success': True, 'data': {'tokens': {'accessToken': 'fresh'}}}}

        env = {'ACTIONBOARD_SCHEMA_REFRESH_TOKEN': 'r', 'ACTIONBOARD_SCHEMA_USERNAME': 'u',
               'ACTIONBOARD_SCHEMA_TOKEN': 'stale'}
        with patch.dict(os.environ, env, clear=True), patch('check_live_schema.graphql_request', fake_request):
            self.assertEqual(access_token('https://edge/graphql'), 'fresh')
        self.assertIn('auth_refreshToken', calls[0][0])
        self.assertEqual(calls[0][1], {'input': {'refreshToken': 'r', 'username': 'u'}})
        self.assertIsNone(calls[0][2])

    def test_failed_refresh_fails_the_check(self):
        def fake_request(*args, **kwargs):
            return {'auth_refreshToken': {'success': False, 'message': 'Refresh Token has expired'}}

        env = {'ACTIONBOARD_SCHEMA_REFRESH_TOKEN': 'r', 'ACTIONBOARD_SCHEMA_USERNAME': 'u'}
        with patch.dict(os.environ, env, clear=True), patch('check_live_schema.graphql_request', fake_request):
            with self.assertRaises(SystemExit) as ctx:
                access_token('https://edge/graphql')
        self.assertIn('expired', str(ctx.exception))

    def test_missing_credentials_fail_the_check(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                access_token('https://edge/graphql')
