"""One Responses HTTPS request, no tools or execution dispatcher, dedicated key only."""
import http.client
import json
import os
import signal
import ssl
from pathlib import Path
from lab.discovery_job import canonical
from lab.literature_discovery import require, sha
from lab.mechanism_precheck import ROOT, PrecheckError

KEY_ENV = 'FREQTRADE_DISCOVERY_OPENAI_API_KEY'
MODEL = 'gpt-5.4-mini-2026-03-17'
ENDPOINT = 'https://api.openai.com/v1/responses'
COST = {'input_token_upper_bound': 400000, 'max_output_tokens': 8192,
        'input_micro_usd_per_million': 750000, 'output_micro_usd_per_million': 4500000,
        'reserve_micro_usd': 336864, 'cumulative_limit_micro_usd': 5000000}


def key_configured(): return bool(os.environ.get(KEY_ENV))


def validate_api_manifest(m):
    require(m.get('model') == MODEL and m.get('endpoint') == ENDPOINT and m.get('cost') == COST,
            'UNREVIEWED_API_COST_OR_MODEL')
    require(m.get('request_bytes') == 262144 and m.get('response_bytes') == 1048576,
            'UNREVIEWED_API_BYTE_LIMIT')
    require(m.get('tools') == [] and m.get('tool_choice') == 'none' and m.get('model_reasoning_effort') == 'medium',
            'UNREVIEWED_API_TOOL_POLICY')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_JSON_KEY'); result[key] = value
        return result
    def invalid(value): raise PrecheckError('NONFINITE_JSON')
    try: return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError): raise PrecheckError('INVALID_JSON') from None


def validate_schema(value, schema):
    kind = schema['type']
    if kind == 'object':
        require(isinstance(value, dict) and set(value) == set(schema['required']), 'INVALID_PROVIDER_SCHEMA')
        for key, child in schema['properties'].items(): validate_schema(value[key], child)
    elif kind == 'array':
        require(isinstance(value, list) and schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 100), 'INVALID_PROVIDER_SCHEMA')
        for item in value: validate_schema(item, schema['items'])
    elif kind == 'string':
        require(isinstance(value, str) and schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 4000), 'INVALID_PROVIDER_SCHEMA')
        require('enum' not in schema or value in schema['enum'], 'INVALID_PROVIDER_SCHEMA')
    else: raise PrecheckError('UNSUPPORTED_SCHEMA_TYPE')


def schema_for(m):
    path = ROOT / 'docs/protocols/issue137-proposals-schema-v1.json'
    require(sha(path.read_bytes()) == m['proposal_schema_sha256'], 'SCHEMA_DRIFT')
    return strict_json(path.read_bytes())


def build_request(prompt, m):
    validate_api_manifest(m)
    require(isinstance(prompt, bytes) and len(prompt) <= m['prompt_bytes'], 'PROMPT_TOO_LARGE')
    payload = dict(model=MODEL, input=prompt.decode('utf-8'), tools=[], tool_choice='none',
        reasoning={'effort': 'medium'}, max_output_tokens=COST['max_output_tokens'],
        text={'format': {'type': 'json_schema', 'name': 'literature_proposals', 'strict': True, 'schema': schema_for(m)}},
        store=False, stream=False, background=False, truncation='disabled', service_tier='default')
    raw = canonical(payload)
    require(len(raw) <= m['request_bytes'], 'API_REQUEST_TOO_LARGE')
    return raw


def post_once(body, seconds, cap):
    # Normal program access to its dedicated secret. No auth files, fallback env,
    # proxy configuration, log output, subprocess or tool dispatch is consulted.
    key = os.environ.get(KEY_ENV)
    require(bool(key) and '\n' not in key and '\r' not in key, 'MISSING_API_KEY')
    connection = http.client.HTTPSConnection('api.openai.com', timeout=seconds, context=ssl.create_default_context())
    def expired(*args): raise TimeoutError('API_TIMEOUT')
    old = signal.signal(signal.SIGALRM, expired); signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        connection.request('POST', '/v1/responses', body=body,
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        require(response.status == 200, 'API_HTTP_' + str(response.status))
        require(response.getheader('Content-Encoding', 'identity') == 'identity', 'API_ENCODING_BLOCKED')
        raw = response.read(cap + 1)
        require(len(raw) <= cap, 'API_RESPONSE_TOO_LARGE')
        return raw
    except (http.client.HTTPException, OSError): raise PrecheckError('API_TRANSPORT_UNKNOWN') from None
    finally:
        connection.close(); key = None
        signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, old)


def parse_response(raw, m):
    require(isinstance(raw, bytes) and len(raw) <= m['response_bytes'], 'API_RESPONSE_TOO_LARGE')
    result = strict_json(raw)
    require(isinstance(result, dict) and result.get('status') == 'completed' and result.get('error') is None
            and result.get('incomplete_details') is None, 'API_NOT_COMPLETED')
    require(result.get('model') == MODEL, 'API_MODEL_MISMATCH')
    outputs = result.get('output')
    require(isinstance(outputs, list) and 1 <= len(outputs) <= 8, 'API_NON_MESSAGE_OUTPUT')
    messages = []
    for output in outputs:
        require(isinstance(output, dict), 'API_NON_MESSAGE_OUTPUT')
        if output.get('type') == 'reasoning':
            require(set(output) <= {'id', 'type', 'summary', 'content', 'encrypted_content', 'status'}, 'API_REASONING_SCHEMA')
            require(isinstance(output.get('id'), str) and isinstance(output.get('summary'), list), 'API_REASONING_SCHEMA')
            for part in output['summary']:
                require(isinstance(part, dict) and set(part) == {'type', 'text'} and part['type'] == 'summary_text'
                        and isinstance(part['text'], str), 'API_REASONING_SCHEMA')
            if 'content' in output and output['content'] is not None:
                require(isinstance(output['content'], list), 'API_REASONING_SCHEMA')
                for part in output['content']:
                    require(isinstance(part, dict) and set(part) == {'type', 'text'} and part['type'] == 'reasoning_text'
                            and isinstance(part['text'], str), 'API_REASONING_SCHEMA')
            require(output.get('encrypted_content') is None or isinstance(output['encrypted_content'], str), 'API_REASONING_SCHEMA')
            require(output.get('status') in (None, 'completed'), 'API_REASONING_SCHEMA')
            # Never add reasoning/summary/encrypted content to the candidate or log.
        elif output.get('type') == 'message': messages.append(output)
        else: raise PrecheckError('API_NON_MESSAGE_OUTPUT')
    require(len(messages) == 1, 'API_NON_MESSAGE_OUTPUT')
    item = messages[0]
    require(isinstance(item, dict) and item.get('type') == 'message' and item.get('role') == 'assistant'
            and item.get('status') == 'completed', 'API_NON_MESSAGE_OUTPUT')
    content = item.get('content')
    require(isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
            and content[0].get('type') == 'output_text' and isinstance(content[0].get('text'), str), 'API_REFUSAL_OR_NON_TEXT')
    text = content[0]['text'].encode(); require(len(text) <= 262144, 'RESULT_TOO_LARGE')
    proposals = strict_json(text); validate_schema(proposals, schema_for(m))
    usage = result.get('usage')
    require(isinstance(usage, dict) and type(usage.get('input_tokens')) is int
            and type(usage.get('output_tokens')) is int, 'API_USAGE_UNKNOWN')
    inp, out = usage['input_tokens'], usage['output_tokens']
    require(0 <= inp <= COST['input_token_upper_bound'] and 0 <= out <= COST['max_output_tokens'], 'API_USAGE_BOUND_EXCEEDED')
    # Round UP to whole micro-dollars; no discount assumption and no refund.
    actual = (inp * COST['input_micro_usd_per_million'] + out * COST['output_micro_usd_per_million'] + 999999) // 1000000
    return proposals, {'status': 'COMPLETED', 'input_tokens': inp, 'output_tokens_including_reasoning': out,
        'model': MODEL, 'estimated_micro_usd': actual, 'reserved_micro_usd': COST['reserve_micro_usd'],
        'response_sha256': sha(raw), 'refund': False}


class ResponsesProvider:
    def __init__(self, manifest): self.manifest = manifest
    def preflight(self, workspace):
        validate_api_manifest(self.manifest)
        require(key_configured(), 'MISSING_API_KEY')
        return {'key_configured': True, 'endpoint': ENDPOINT, 'tools': [], 'tool_choice': 'none'}
    def __call__(self, prompt, workspace, seconds, cap):
        raw = build_request(prompt, self.manifest)
        return parse_response(post_once(raw, seconds, cap), self.manifest)
