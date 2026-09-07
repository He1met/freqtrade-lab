"""Offline bounded literature accounting and conservative mechanism-card precheck.

All narrative classifications are supplied claims, never instructions or proof.
"""
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from lab.mechanism_precheck import ROOT, PrecheckError, load_knowledge, precheck, utc

PROTOCOL = ROOT / 'docs/protocols/issue135-literature-discovery-v1.json'
PROTOCOL_SHA = '7ee118f0749957f0fa6fde8eec098238f84a3160d0c2de6d3afde41d0b991501'


def require(condition, message):
    if not condition:
        raise PrecheckError(message)


def string(value):
    require(isinstance(value, str) and 0 < len(value) <= 4000, 'invalid text')
    return value


def strings(value):
    require(isinstance(value, list) and 0 < len(value) <= 30, 'invalid text list')
    return [string(v) for v in value]


def read_bytes(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'input too large')
    return raw


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_batch(path):
    raw = read_bytes(path, 262144)
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise PrecheckError('nonfinite JSON')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid), sha(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PrecheckError('invalid JSON') from exc


def canonical_url(value):
    string(value)
    require(not any(ord(c) <= 32 for c in value), 'invalid URL whitespace')
    try:
        parts = urlsplit(value)
        require(parts.scheme == 'https' and parts.hostname and not parts.username
                and not parts.password and parts.port in (None, 443), 'HTTPS source URL required')
    except ValueError as exc:
        raise PrecheckError('invalid URL') from exc
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit(('https', parts.hostname.lower(), parts.path or '/', urlencode(sorted(query)), ''))


def verify_cache(root, name, expected):
    string(name)
    require(Path(name).name == name and name not in ('.', '..'), 'cache basename required')
    path = (Path(root) / name).resolve()
    require(path.is_relative_to(Path(root).resolve()), 'cache path escape')
    require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'invalid SHA')
    require(sha(read_bytes(path, 1048576)) == expected, 'cache SHA drift')


def fingerprint(proposal, fields):
    def normalize(text):
        text = unicodedata.normalize('NFKC', text).casefold()
        for asset in sorted(proposal['assets'], key=len, reverse=True):
            text = re.sub(r'(?<!\w)' + re.escape(asset.casefold()) + r'(?!\w)', '<asset>', text)
        text = re.sub(r'\d+(?:\.\d+)?', '<number>', text)
        return ' '.join(text.split())
    values = {key: sorted(normalize(v) for v in proposal[key]) if isinstance(proposal[key], list)
              else normalize(proposal[key]) for key in fields}
    return sha(json.dumps(values, sort_keys=True, ensure_ascii=False).encode())


def discover(batch, cache_root, *, protocol_path=PROTOCOL, protocol_sha=PROTOCOL_SHA):
    """Validate submitted accounting; no authority to fetch or enforce external calls."""
    require(sha(Path(protocol_path).read_bytes()) == protocol_sha, 'protocol SHA drift')
    protocol = json.loads(Path(protocol_path).read_bytes())
    for name, expected in protocol['prior_knowledge'].items():
        require(sha((ROOT / name).read_bytes()) == expected, 'prior knowledge SHA drift')
    knowledge = load_knowledge()
    require(isinstance(batch, dict) and batch.get('schema') == 'literature-discovery-batch-v1'
            and batch.get('batch_id') == protocol['batch_id']
            and batch.get('protocol_sha256') == protocol_sha, 'invalid batch binding')
    for key, limit in [('queries', 'search_queries'), ('sources', 'source_records'),
                       ('page_attempts', 'page_attempts'), ('proposals', 'proposals')]:
        require(isinstance(batch.get(key), list) and len(batch[key]) <= protocol['limits'][limit],
                'invalid or overbudget ' + key)
    queries = {}
    for query in batch['queries']:
        require(isinstance(query, dict), 'invalid query')
        key = string(query.get('id'))
        require(key not in queries and isinstance(query.get('query'), str)
                and query['query'] in protocol['queries'] and query.get('status') in ('COMPLETED', 'FAILED'), 'invalid query ledger')
        utc(query.get('recorded_at_utc'))
        queries[key] = query
    log = batch.get('search_log')
    require(isinstance(log, dict) and type(log.get('counted_queries')) is int
            and log['counted_queries'] == len(queries), 'invalid search log')
    verify_cache(cache_root, log.get('cache_file'), log.get('sha256'))
    attempts = []
    for attempt in batch['page_attempts']:
        require(isinstance(attempt, dict), 'invalid page attempt')
        key = string(attempt.get('source_id'))
        require(attempt.get('status') in ('READABLE', 'FETCH_FAILED'), 'invalid attempt status')
        utc(attempt.get('recorded_at_utc'))
        attempts.append((key, attempt['status']))
    sources = {}; groups = []
    for source in batch['sources']:
        require(isinstance(source, dict), 'invalid source')
        key = string(source.get('id'))
        require(key not in sources, 'duplicate source id')
        url = canonical_url(source.get('canonical_url'))
        for field in ('title', 'scope', 'summary', 'support_locator', 'access_time_basis'):
            string(source.get(field))
        strings(source.get('authors_or_institution'))
        refs = strings(source.get('query_ids'))
        require(all(r in queries for r in refs), 'unknown source query')
        date = source.get('publication_date')
        require(date is None or isinstance(date, str) and re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', date), 'invalid publication date')
        utc(source.get('accessed_at_utc'))
        status = source.get('status')
        require((key, status) in attempts and status in ('READABLE', 'FETCH_FAILED'), 'source missing matching attempt')
        expected_kind = protocol.get('readable_content_kind', 'WEB_TOOL_EXTRACT_NOT_FULL_HTML') if status == 'READABLE' else protocol.get('failed_content_kind', 'WEB_TOOL_FETCH_ERROR_NOT_PAPER_CONTENT')
        require(source.get('content_kind') == expected_kind, 'error receipt is not paper content')
        verify_cache(cache_root, source.get('cache_file'), source.get('content_sha256'))
        sources[key] = source
        # Merge bridging URL/hash overlaps, keeping failed/readable receipts separate.
        matching = [g for g in groups if g['status'] == status and (url in g['urls'] or source['content_sha256'] in g['hashes'])]
        group = {'ids': [key], 'urls': [url], 'hashes': [source['content_sha256']], 'status': status}
        for old in matching:
            for field in ('ids', 'urls', 'hashes'):
                group[field] += old[field]
            groups.remove(old)
        groups.append(group)
    require(all(key in sources for key, _ in attempts), 'attempt without source record')
    for key in sources:
        require(attempts[[k for k, _ in attempts].index(key)][1] == sources[key]['status'], 'inconsistent attempt receipt')
    cards = []; rejected = []; seen = {}; ids = set()
    for proposal in batch['proposals']:
        require(isinstance(proposal, dict), 'invalid proposal')
        key = string(proposal.get('id'))
        require(key not in ids, 'duplicate proposal id'); ids.add(key)
        for field in ('family', 'economic_explanation', 'signal', 'direction', 'holding_scale',
                      'falsification', 'prior_family_comparison'):
            string(proposal.get(field))
        for field in ('assets', 'execution_cost_dependencies', 'source_does_not_support', 'unknowns'):
            strings(proposal.get(field))
        require(len(set(proposal['assets'])) == len(proposal['assets']), 'duplicate asset')
        require(isinstance(proposal.get('parameters'), dict), 'invalid parameters')
        require(proposal.get('classification_basis') == 'MODEL_INFERENCE_NEEDS_REVIEW', 'classification is inference only')
        support = proposal.get('source_support')
        require(isinstance(support, list) and 0 < len(support) <= 12, 'source support required')
        usable = True
        for claim in support:
            require(isinstance(claim, dict), 'invalid source claim')
            source_id = string(claim.get('source_id'))
            require(source_id in sources, 'unknown supporting source')
            string(claim.get('claim')); string(claim.get('locator'))
            usable &= sources[source_id]['status'] == 'READABLE'
        if not usable:
            rejected.append(dict(id=key, reason='FETCH_ERROR_CANNOT_SUPPORT_CARD')); continue
        fp = fingerprint(proposal, protocol['fingerprint_fields'])
        if fp in seen:
            rejected.append(dict(id=key, reason='SAME_FAMILY_VARIANT', duplicate_of=seen[fp])); continue
        seen[fp] = key
        card = dict(schema='mechanism-precheck-card-v1', candidate_id=key,
            idea=proposal['economic_explanation'], strategy_family=proposal['family'],
            expected_failure_mode=proposal['falsification'], mechanism_id=key,
            knowledge_refs=[v['id'] for v in knowledge['lessons']], exchange='UNKNOWN',
            instrument_type='UNKNOWN', symbols=proposal['assets'], purpose='EXPLORATORY_TRAINING',
            window=None, reserve_source_sha256=None, sizing_case_id=None,
            sample_evidence_type='UNKNOWN', claimed_expected_trades=None,
            claims_real_qualification=False, native_calls_requested=0, reuse_keys=[])
        # No free-text assertion can certify an execution domain. These two structures
        # require capabilities absent from the scoped single-venue directional adapter.
        reasons = {'DELTA_NEUTRAL_LONG_SPOT_SHORT_FUTURE': 'MULTI_LEG_SPOT_FUTURE_BASIS_FINANCING_REQUIRED',
                   'HEDGED_BUY_CHEAP_SELL_EXPENSIVE': 'CROSS_VENUE_INVENTORY_EXECUTION_REQUIRED'}
        reason = reasons.get(proposal['direction'], 'PROFILE_EXECUTION_BINDING_NOT_VERIFIED')
        cards.append(dict(proposal=proposal, fingerprint=fp, mechanism_card=card, precheck=precheck(card),
            applicability=dict(status='BLOCKED_CURRENT_EXECUTION_DOMAIN', reason=reason,
                binding_verified=False, executable_card=False), independent_mechanism='UNKNOWN',
            family_relation='RELATED_PRIOR_FAMILY_INFERENCE' if proposal['family'] in ('trend', 'reversal', 'funding')
                            else 'UNPROVEN_RELATION_NEEDS_REVIEW'))
    require(len(cards) <= protocol['limits']['cards'], 'card budget exceeded')
    return dict(schema='literature-discovery-result-v1', protocol_sha256=protocol_sha,
        counts=dict(queries=len(queries), page_attempts=len(attempts), source_records=len(sources),
                    readable_sources=sum(s['status'] == 'READABLE' for s in sources.values()),
                    cards=len(cards), executable_cards=0),
        source_groups=groups, sources=list(sources.values()), cards=cards, rejected=rejected,
        status='KNOWLEDGE_ONLY_EXECUTION_BLOCKED', execution_authorized=False,
        source_truth_verified=False, semantic_review='MODEL_INFERENCE_REQUIRES_REVIEW',
        accounting_scope='SUBMITTED_LEDGER_ONLY_EXTERNAL_WEB_BUDGET_SUPERVISED_BY_TASK',
        next_dependency='STATIC_CARD_TO_EXISTING_PROFILE_COMPATIBILITY_REVIEW_NO_GENERATION')
