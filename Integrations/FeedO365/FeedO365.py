from typing import Dict, List, Tuple

import uuid
import urllib3

from CommonServerPython import *

# disable insecure warnings
urllib3.disable_warnings()
INTEGRATION_NAME = 'O365Feed'
PROTOTYPE_TO_URL = {
    "o365-api.china-common": "https://endpoints.office.com/endpoints/China?ServiceAreas=Common",
    "o365-api.china-exchange": "https://endpoints.office.com/endpoints/China?ServiceAreas=Exchange",
    "o365-api.china-sharepoint": "https://endpoints.office.com/endpoints/China?ServiceAreas=SharePoint",
    "o365-api.china-skype": "https://endpoints.office.com/endpoints/China?ServiceAreas=Skype",
    "o365-api.germany-any": "https://endpoints.office.com/endpoints/Germany?ServiceAreas=Any",
    "o365-api.germany-common": "https://endpoints.office.com/endpoints/Germany?ServiceAreas=Common",
    "o365-api.germany-exchange": "https://endpoints.office.com/endpoints/Germany?ServiceAreas=Exchange",
    "o365-api.germany-sharepoint": "https://endpoints.office.com/endpoints/Germany?ServiceAreas=SharePoint",
    "o365-api.germany-skype": "https://endpoints.office.com/endpoints/Germany?ServiceAreas=Skype",
    "o365-api.usgovdod-any": "https://endpoints.office.com/endpoints/USGovDoD?ServiceAreas=Any",
    "o365-api.usgovdod-common": "https://endpoints.office.com/endpoints/USGovDoD?ServiceAreas=Common",
    "o365-api.usgovdod-exchange": "https://endpoints.office.com/endpoints/USGovDoD?ServiceAreas=Exchange",
    "o365-api.usgovdod-sharepoint": "https://endpoints.office.com/endpoints/USGovDoD?ServiceAreas=SharePoint",
    "o365-api.usgovdod-skype": "https://endpoints.office.com/endpoints/USGovDoD?ServiceAreas=Skype",
    "o365-api.usgovgcchigh-any": "https://endpoints.office.com/endpoints/USGovGCCHigh?ServiceAreas=Any",
    "o365-api.usgovgcchigh-common": "https://endpoints.office.com/endpoints/USGovGCCHigh?ServiceAreas=Common",
    "o365-api.usgovgcchigh-exchange": "https://endpoints.office.com/endpoints/USGovGCCHigh?ServiceAreas=Exchange",
    "o365-api.usgovgcchigh-sharepoint": "https://endpoints.office.com/endpoints/USGovGCCHigh?ServiceAreas=SharePoint",
    "o365-api.usgovgcchigh-skype": "https://endpoints.office.com/endpoints/USGovGCCHigh?ServiceAreas=Skype",
    "o365-api.worldwide-any": "https://endpoints.office.com/endpoints/Worldwide?ServiceAreas=Any",
    "o365-api.worldwide-common": "https://endpoints.office.com/endpoints/Worldwide?ServiceAreas=Common",
    "o365-api.worldwide-exchange": "https://endpoints.office.com/endpoints/Worldwide?ServiceAreas=Exchange",
    "o365-api.worldwide-sharepoint": "https://endpoints.office.com/endpoints/Worldwide?ServiceAreas=SharePoint",
    "o365-api.worldwide-skype": "https://endpoints.office.com/endpoints/Worldwide?ServiceAreas=Skype",
}


class Client(BaseClient):
    """
    Client to use in the O365 Feed integration. Overrides BaseClient.
    Office 365 IP address and URL web service announcement:
    https://techcommunity.microsoft.com/t5/Office-365-Blog/Announcing-Office-365-endpoint-categories-and-Office-365-IP/ba-p/177638
    """
    def __init__(self, url_list: List[str], indicator: str, insecure: bool = False, proxy: bool = False):
        """
        Implements class for O365 feeds.
        :param url_list: URL of the feed.
        :param indicator: the JSON attribute to use as indicator. Can be ips or urls. Default: ips
        :param insecure: boolean, if *false* feed HTTPS server certificate is verified. Default: *false*
        :param proxy: boolean, if *false* feed HTTPS server certificate will not use proxies. Default: *false*
        """
        super().__init__(base_url=url_list, verify=insecure, proxy=proxy)
        self.indicator = indicator

    def build_iterator(self) -> List:
        """Retrieves all non entries from the feed.

        Returns:
            A list of objects, containing the indicators.
        """
        result = []
        for url in self._base_url:
            try:
                response = requests.get(
                    url=url,
                    verify=self._verify
                )
                response.raise_for_status()
                data = response.json()
                result.extend([i for i in data if 'ips' in i or 'urls' in i])  # filter empty entries
            except requests.exceptions.SSLError as err:
                demisto.debug(str(err))
                raise Exception(f'Connection error in the API call to O365.\n'
                                f'Check your not secure parameter.\n\n{err}')
            except requests.ConnectionError as err:
                demisto.debug(str(err))
                raise Exception(f'Connection error in the API call to O365.\n'
                                f'Check your Server URL parameter.\n\n{err}')
            except requests.exceptions.HTTPError as err:
                demisto.debug(str(err))
                raise Exception(f'Error issuing the request call to O365.\n\n{err}')
            except ValueError as err:
                demisto.debug(str(err))
                raise ValueError(f'Could not parse returned data to Json. \n\nError massage: {err}')
        return result


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
    indicator_type_lower = indicator_type.lower()
    indicators = []
    raw_response = []
    limit = int(demisto.args().get('limit')) if 'limit' in demisto.args() else 10
    iterator = [i for i in iterator if indicator_type_lower in i]  # filter indicator_type specific entries
    iterator = iterator[:limit]
    for item in iterator:
        values = item.get(indicator_type_lower)
        raw_data = {'type': indicator_type[:-1]}
        if values:
            for value in values:
                raw_data['value'] = value
                indicators.append({
                    "Value": value,
                    "Type": indicator_type[:-1],
                    'rawJSON': {"Value": value, "Type": indicator_type[:-1]}
                })
                raw_response.append(raw_data)
    human_readable = tableToMarkdown('Indicators from O365 Feed:', indicators,
                                     headers=['Value', 'Type'], removeNull=True)

    return human_readable, {'O365.Indicator': indicators}, raw_response


def fetch_indicators_command(client: Client, *_) -> List[Dict]:
    """Fetches indicators from the feed to the indicators tab.

    Args:
        client: Client object with request

    Returns:
        Indicators.
    """
    indicator_type = client.indicator
    demisto.info('11111')
    demisto.info(str(demisto.params()))
    demisto.info(str(indicator_type))
    indicator_type_lower = indicator_type.lower()
    iterator = client.build_iterator()
    indicators = []
    for item in iterator:
        values = item.get(indicator_type_lower)
        raw_data = {'type': indicator_type[:-1]}
        if values:
            for value in values:
                raw_data['value'] = value
                indicators.append({
                    "value": value,
                    "type": indicator_type[:-1],
                    "rawJSON": raw_data,
                })
    return indicators


def main():
    """
    PARSE AND VALIDATE INTEGRATION PARAMS
    """
    unique_id = str(uuid.uuid4())
    prototype_list = argToList(demisto.params().get('url'))
    url_list = [f"{PROTOTYPE_TO_URL[prototype]}&ClientRequestId={unique_id}" for prototype in prototype_list]
    indicator = demisto.params().get('indicator')
    insecure = demisto.params().get('insecure', False)
    proxy = demisto.params().get('proxy') == 'true'

    client = Client(url_list, indicator, insecure, proxy)
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
