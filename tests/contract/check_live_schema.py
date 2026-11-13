"""Validate every CLI GraphQL document against introspection through the edge proxy.

Requires graphql-core (CI only). The only mutation sent is the token refresh. Missing
credentials, network errors and unavailable introspection fail the check rather than skip it.

Credentials, in order:
  ACTIONBOARD_SCHEMA_REFRESH_TOKEN + ACTIONBOARD_SCHEMA_USERNAME  (for CI: a fresh access token
      is minted on every run; the username is the account's user id / cognito:username, not its email)
  ACTIONBOARD_SCHEMA_TOKEN  (an access token, for one-off local runs; it expires after an hour)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/skills/mission-report/scripts'))
from actionboard_cli import operations
from actionboard_cli.api import graphql_request
from actionboard_cli.common import DEFAULT_EDGE_PROXY_URL
from actionboard_cli.operations import MUTATION_REFRESH
from graphql import build_client_schema, get_introspection_query, parse, validate


def validate_operations(schema):
    errors = []
    documents = {name: value for name, value in vars(operations).items()
                 if name.startswith(('QUERY_', 'MUTATION_'))}
    if not documents:
        raise RuntimeError('No CLI GraphQL operations found')
    for name, document in sorted(documents.items()):
        errors.extend(f'{name}: {error.message}' for error in validate(schema, parse(document)))
    return errors


def access_token(endpoint):
    refresh_token = os.environ.get('ACTIONBOARD_SCHEMA_REFRESH_TOKEN')
    username = os.environ.get('ACTIONBOARD_SCHEMA_USERNAME')
    if refresh_token and username:
        data = graphql_request(endpoint, None, MUTATION_REFRESH,
                               {'input': {'refreshToken': refresh_token, 'username': username}})
        result = data.get('auth_refreshToken') or {}
        token = ((result.get('data') or {}).get('tokens') or {}).get('accessToken')
        if not result.get('success') or not token:
            # The message never echoes the token; it is usually an expired or revoked refresh token.
            raise SystemExit('Token refresh failed: %s. Replace the ACTIONBOARD_SCHEMA_REFRESH_TOKEN secret.'
                             % (result.get('message') or 'no access token returned'))
        return token
    token = os.environ.get('ACTIONBOARD_SCHEMA_TOKEN')
    if token:
        return token
    raise SystemExit('Set ACTIONBOARD_SCHEMA_REFRESH_TOKEN and ACTIONBOARD_SCHEMA_USERNAME '
                     '(or ACTIONBOARD_SCHEMA_TOKEN for a one-off local run) for live schema validation')


def main():
    endpoint = os.environ.get('ACTIONBOARD_SCHEMA_PROXY_URL', DEFAULT_EDGE_PROXY_URL).rstrip('/') + '/graphql'
    token = access_token(endpoint)
    data = graphql_request(endpoint, None, get_introspection_query(), bearer_token=token)
    errors = validate_operations(build_client_schema(data))
    if errors:
        raise SystemExit('\n'.join(errors))
    print('All CLI operations match the live schema')


if __name__ == '__main__':
    main()
