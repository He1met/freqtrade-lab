"""Read-only source integrity and native-admission boundary for Issue139."""
import hashlib
import json
from pathlib import Path


class BindingError(ValueError):pass

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def deny_network(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.bind'):
        raise BindingError('spot execution network prohibited')

def validate_sources(manifest):
    # Check control/manifest first, then all bytes before parsing any prices.
    for p,h in manifest['bindings'].items():
        if sha(p)!=h:raise BindingError('bound input changed: '+p)
    for source in manifest['sources']:
        if sha(source['path'])!=source['sha256']:raise BindingError('source tampered: '+source['path'])
    if len(manifest['sources'])!=39 or len({s['path'] for s in manifest['sources']})!=39:raise BindingError('exact39 sources required')
    if manifest['source_grade']!='SOURCE_INVENTORY_COMPLETE_NOT_EXECUTION_ADMITTED':raise BindingError('source grade overclaim')
    return True

def audit_native_fill(fill,source_opens,expected_inventory_after):
    """Reject native/reference disagreement; never overwrite native fills."""
    key=(fill['symbol'],fill['hour'])
    if key not in source_opens:raise BindingError('native fill on missing source open')
    if fill['inventory_after']!=expected_inventory_after:raise BindingError('native base inventory/fee mismatch')
    if fill.get('exit_reason')=='force_exit':raise BindingError('unapproved terminal force exit')
    return True


def preflight(manifest):
    validate_sources(manifest)
    if manifest.get('market_execution_authorized') is not False:raise BindingError('current package cannot grant its own execution')
    return dict(status='BLOCKED_NATIVE_RECONCILIATION',source_integrity='PASS',native_calls=0,
                budget_reservations=0,economic_result=None,
                reason='Pinned native entry quote-fee accounting and terminal handling are not bound to base-fee/dust/open-terminal spot contract; reference model is not native matching')
