from __future__ import absolute_import

from typing import Dict, List, Tuple

import urllib3

from CommonServerPython import *

# disable insecure warnings
urllib3.disable_warnings()
INTEGRATION_NAME = 'O365Feed'


class Client(BaseClient):
    """
    Client to use in the O365 Feed integration. Overrides BaseClient.
    Office 365 IP address and URL web service announcement:
    https://techcommunity.microsoft.com/t5/Office-365-Blog/Announcing-Office-365-endpoint-categories-and-Office-365-IP/ba-p/177638
    """
    def __init__(self, url: str, indicator_type: str, credentials: Dict[str, str],
                 verify: bool = False, proxy: bool = False):
        """
        Implements class for miners of O365 feeds.
        :param url: URL of the feed.
        :param indicator_type: the JSON attribute to use as indicator. Can be ips or urls. Default: ips
        :param credentials:
            username: username for BasicAuth authentication
            password: password for BasicAuth authentication
        :param verify: boolean, if *false* feed HTTPS server certificate is verified. Default: *false*
        :param proxy: boolean, if *false* feed HTTPS server certificate will not use proxies. Default: *false*
        """
        super().__init__(base_url=url, verify=verify, proxy=proxy)
        if not credentials:
            credentials = {}
        self.username = credentials.get('identifier', None)
        self.password = credentials.get('password', None)
        self.indicator_type = indicator_type

    def build_iterator(self) -> List:
        """Retrieves all non entries from the feed.

        Returns:
            A list of objects, containing the indicators.
        """
        auth = None
        if self.username is not None and self.password is not None:
            auth = (self.username, self.password)

        response = requests.get(
            url=self._base_url,
            verify=self._verify,
            auth=auth
        )
        try:
            response.raise_for_status()

            data = response.json()
            result = [i for i in data if 'ips' in i or 'urls' in i]  # filter empty entries
            return result

        except ValueError as err:
            raise ValueError(f'Could not parse returned data to Json. \n\nError massage: {err}')


def batch_indicators(sequence, batch_size=1) -> List:
    """Batch the indicators to balance load on the server.

    Args:
        sequence: all items
        batch_size: how many items to batch

    Returns:
        A List of batch_size of items.
    """
    sequence_length = len(sequence)
    for i in range(0, sequence_length, batch_size):
        yield sequence[i:min(i + batch_size, sequence_length)]


def test_module(client: Client) -> Tuple[str, Dict, Dict]:
    """Builds the iterator to check that the feed is accessible.
    Args:
        client: Client object.

    Returns:
        Outputs.
    """
    client.build_iterator()
    return 'ok', {}, {}


def get_indicators_command(client: Client, indicator_type: str) -> Tuple[str, Dict, Dict]:
    """Retrieves indicators from the feed to the war-room.

    Args:
        client: Client object with request
        indicator_type: indicator_type to be retrieved.

    Returns:
        Outputs.
    """
    iterator = client.build_iterator()
    indicators = []
    raw_response = []
    limit = int(demisto.args().get('limit')) if 'limit' in demisto.args() else 100
    iterator = [i for i in iterator if indicator_type in i]  # filter indicator_type specific entries
    iterator = iterator[:limit]
    for item in iterator:
        values = item.get(indicator_type)
        raw_json = {'type': indicator_type[:-1]}
        if values:
            for value in values:
                raw_json['value'] = value
                indicators.append({
                    "Value": value,
                    "Type": indicator_type,
                })
                raw_response.append(raw_json)
    human_readable = tableToMarkdown('Indicators from O365 Feed:', indicators,
                                     headers=['Value', 'Type'], removeNull=True)
    return human_readable, {}, raw_response


def fetch_indicators_command(client: Client) -> List[Dict]:
    """Fetches indicators from the feed to the indicators tab.

    Args:
        client: Client object with request

    Returns:
        Indicators.
    """
    indicator_type = client.indicator_type
    iterator = client.build_iterator()
    indicators = []
    for item in iterator:
        values = item.get(indicator_type)
        raw_json = {'type': indicator_type[:-1]}
        if values:
            for value in values:
                raw_json['value'] = value
                indicators.append({
                    "value": value,
                    "type": indicator_type,
                    "rawJSON": raw_json,
                })
    return indicators


def main():
    """
    PARSE AND VALIDATE INTEGRATION PARAMS
    """
    url = demisto.params().get('url')
    indicator_type = demisto.params().get('indicator_type')
    credentials = demisto.params().get('credentials', {})
    verify = demisto.params().get('verify', False)
    proxy = demisto.params().get('proxy') == 'true'

    client = Client(url, indicator_type, credentials, verify, proxy)
    command = demisto.command()
    demisto.info(f'Command being called is {command}')

    try:
        if command == 'test-module':
            readable_output, outputs, raw_response = test_module(client)
            return_outputs(readable_output, outputs, raw_response)

        elif command == 'get-indicators':
            readable_output, outputs, raw_response = get_indicators_command(client, demisto.args()['indicator_type'])
            return_outputs(readable_output, outputs, raw_response)

        elif command == 'fetch-indicators':
            indicators = fetch_indicators_command(client)
            for batch in batch_indicators(indicators, batch_size=2000):
                demisto.createIndicators(batch)

        else:
            raise NotImplementedError(f'Command {command} is not implemented.')

    except Exception as err:
        err_msg = f'Error in {INTEGRATION_NAME} Integration. [{err}]'
        return_error(err_msg)


if __name__ in ['__main__', 'builtin', 'builtins']:
    main()
