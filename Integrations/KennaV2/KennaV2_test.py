import pytest

from KennaV2 import create_dict, search_vulnerabilities, get_connectors, Client, \
    search_fixes, search_assets, get_asset_vulenrabilities
from Tests_Data.ExpectedResult import VULNERABILITIES_SEARCH_EXPECTED, GET_CONNECTORS_EXPECTED, SEARCH_FIXES_EXPECTED, \
    SEARCH_ASSETS_EXPECTED,GET_ASSETS_VULNERABILITIES_EXPECTED
from Tests_Data.RawData import VULNERABILITIES_SEARCH_RESPONSE, GET_CONNECTORS_RESPONSE, SEARCH_FIXES_RESPONSE, \
    SEARCH_ASSETS_RESPONSE,GET_ASSETS_VULNERABILITIES_RESPONSE


def test_create_dict():
    raw = [{
        'id': '12',
        'cve-id': 'CVE-AS1255',
        'list': [{
            'list-id': '123'
        }]
    }]
    expected = [{
        'ID': '12',
        'CVE-ID': 'CVE-AS12',
        'List': [{
            'List-ID': '123'
        }]
    }]
    wanted = ['ID', 'CVE-ID', ['List', 'List-ID']]
    actual = ['id', 'cve-id', ['list', 'list-id']]
    to_dict = create_dict(raw, wanted, actual)
    assert to_dict == expected

@pytest.mark.parametrize('command, args, response, expected_result', [
    (search_vulnerabilities, {}, VULNERABILITIES_SEARCH_RESPONSE, VULNERABILITIES_SEARCH_EXPECTED),
    (get_connectors, {}, GET_CONNECTORS_RESPONSE, GET_CONNECTORS_EXPECTED),
    (search_fixes, {}, SEARCH_FIXES_RESPONSE, SEARCH_FIXES_EXPECTED),
    (search_assets, {}, SEARCH_ASSETS_RESPONSE, SEARCH_ASSETS_EXPECTED),
    (get_asset_vulenrabilities, {'id': '3'}, GET_ASSETS_VULNERABILITIES_RESPONSE, GET_ASSETS_VULNERABILITIES_EXPECTED),
])
def test_commands(command, args, response, expected_result, mocker):
    client = Client('https://api.kennasecurity.com', 'api', 'use_ssl', 'use_proxy')
    mocker.patch.object(client, '_http_request', return_value=response)
    result = command(client, args)
    assert expected_result == result[1]