"""Synthetic hand calculations and finite common-ray oracle; no market runs."""
from decimal import Decimal, localcontext, ROUND_UP, ROUND_DOWN, Inexact, Rounded
from fractions import Fraction as F
import pytest
from lab.portfolio_causal import PAIRS
from lab.portfolio_short import reserve_additions, configuration
from lab.portfolio_source import SourceError


def pair(x, y):
    return dict(zip(PAIRS, (str(x), str(y))))


def run(a, d, px=None, step=None, equity='1000', cost='base'):
    return reserve_additions(equity, a, d, px or pair(100, 100),
                             step or pair('.001', '.001'), configuration('B', cost))


@pytest.mark.parametrize('precision,rounding', [(6, ROUND_UP), (28, ROUND_DOWN), (60, ROUND_UP)])
@pytest.mark.parametrize('desired', [pair('.001',0), pair('-.003','-.002'), pair('.002','.003')])
def test_legal_endpoints_exact_in_all_contexts(precision, rounding, desired):
    with localcontext() as ctx:
        ctx.prec = precision; ctx.rounding = rounding
        ctx.traps[Inexact] = True; ctx.traps[Rounded] = True
        q = run(pair(0,0), desired, pair(60000,3000))
    assert q == {p: Decimal(v) for p,v in desired.items()}


def test_output_coefficient_exceeds_context_without_rounding():
    with localcontext() as ctx:
        ctx.prec = 6; ctx.Emax = 9; ctx.Emin = -9
        ctx.traps[Inexact] = True; ctx.traps[Rounded] = True
        q = run(pair(0,0), pair('-.123456789012345678901234',0), pair(1,1), pair('1e-24','1e-24'))
    assert q[PAIRS[0]] == Decimal('-.123456789012345678901234')


@pytest.mark.parametrize('cost,expected', [('base','3.996'),('stress','3.992')])
def test_two_asset_cost_boundary_hand_calculation(cost, expected):
    # Symmetric x: 100x <= .4(1000 - 200x*c).
    # base x <= 400/100.096; stress <= 400/100.192.
    q = run(pair(0,0), pair(4,4), cost=cost)
    assert q == {p:Decimal(expected) for p in PAIRS}
    c = F('0.0012' if cost=='base' else '0.0024')
    x = F(expected)
    assert 100*x <= F('0.4')*(1000-200*x*c)
    assert 100*(x+F('.001')) > F('0.4')*(1000-200*(x+F('.001'))*c)


def test_existing_short_and_zero_addition():
    a = pair(-1,1)
    assert run(a,a) == {p:Decimal(v) for p,v in a.items()}
    assert run(a,pair(-2,2)) == {PAIRS[0]:Decimal(-2),PAIRS[1]:Decimal(2)}
    # At existing 400 cap, ANY fee-paying addition on other asset breaches cap.
    assert run(pair(4,0),pair(4,1)) == {PAIRS[0]:Decimal(4),PAIRS[1]:Decimal(0)}


def test_existing_exposure_true_bound_and_conservative_projection():
    # a=(1,-1), d=(5,-3), price100, c=.0012.
    # First cap binds: 100+400L <=400-.288L => L=300/400.288.
    # q before projection=(3.997841..., -2.498920...); lot .1.
    for precision in (6,28,60):
        with localcontext() as ctx:
            ctx.prec = precision
            assert run(pair(1,-1),pair(5,-3),step=pair('.1','.1')) == {
                PAIRS[0]:Decimal('3.9'),PAIRS[1]:Decimal('-2.4')}
    # Legal non-grid desired is floored, never enlarged for native minimum.
    assert run(pair(0,0),pair('.0019',0),pair(60000,3000))[PAIRS[0]] == Decimal('.001')


def test_small_finite_oracle_along_common_ray():
    # Choose E so one exact rational ray point is at a cap boundary.
    # Enumerate 101 lambda values with independent direct post-cost predicates.
    # Boundary lambda k/100 is present; oracle chooses last passing point.
    for a0,a1,d0,d1,k in [(0,0,10,10,50),(1,0,9,3,25),(0,-1,-4,-9,75),(2,1,2,7,50)]:
        a=(F(a0),F(a1));d=(F(d0),F(d1));lam=F(k,100)
        q=tuple(a[i]+lam*(d[i]-a[i]) for i in range(2))
        charge=sum(abs(q[i]-a[i])*100*F('.0012') for i in range(2))
        E=max(max(abs(v)*250 for v in q),sum(abs(v)*125 for v in q))+charge
        candidates=[]
        for j in range(101):
            v=tuple(a[i]+F(j,100)*(d[i]-a[i]) for i in range(2))
            net=E-sum(abs(v[i]-a[i])*100*F('.0012') for i in range(2))
            if net>0 and all(abs(x)*100<=F('.4')*net for x in v) and sum(abs(x)*100 for x in v)<=F('.8')*net:
                candidates.append(v)
        expected=candidates[-1]
        # These E decimals terminate; conversion performed in spacious test context.
        with localcontext() as ctx:
            ctx.prec=60
            equity=str(Decimal(E.numerator)/Decimal(E.denominator))
        result=run(pair(*a),pair(*d),step=pair('.01','.01'),equity=equity)
        assert tuple(F(result[p]) for p in PAIRS)==expected


@pytest.mark.parametrize('field', ['equity','actual','desired','prices','steps'])
@pytest.mark.parametrize('bad', ['NaN','sNaN','Infinity','-Infinity','bad'])
def test_nonfinite_and_malformed_fail_closed(field,bad):
    args=dict(equity='1000',actual=pair(0,0),desired=pair(1,1),prices=pair(100,100),steps=pair('.001','.001'),config=configuration('B','base'))
    if field=='equity':args[field]=bad
    else:args[field][PAIRS[0]]=bad
    with pytest.raises(SourceError,match='invalid addition inputs'):
        reserve_additions(**args)


@pytest.mark.parametrize('a,d,px,step,E', [
    (pair(0,0),pair(1,1),pair(0,100),pair('.001','.001'),'1000'),
    (pair(0,0),pair(1,1),pair(100,100),pair(0,'.001'),'1000'),
    (pair(0,0),pair(1,1),pair(100,100),pair('.001','.001'),'0'),
    (pair(1,0),pair(-1,0),pair(100,100),pair('.001','.001'),'1000'),
    (pair(1,0),pair('.9',0),pair(100,100),pair('.001','.001'),'1000'),
    (pair(5,0),pair(6,0),pair(100,100),pair('.001','.001'),'1000'),
    (pair('.0015',0),pair('.0015',0),pair(100,100),pair('.001','.001'),'1000'),
    ({},pair(1,1),pair(100,100),pair('.001','.001'),'1000'),
])
def test_invalid_domain_and_offgrid_reduction_blocked(a,d,px,step,E):
    with pytest.raises(SourceError):run(a,d,px,step,E)


@pytest.mark.parametrize('config', [None, {}, {'mode':'bad'}, dict(configuration('B','base'),fee='NaN')])
def test_invalid_config(config):
    with pytest.raises(SourceError):
        reserve_additions('1000',pair(0,0),pair(1,1),pair(100,100),pair('.001','.001'),config)


def test_exact_legal_cap_endpoint_and_empty_portfolio():
    # 800 added notional costs .96; net1000 makes each400 exactly legal.
    for precision in (6,28,60):
        with localcontext() as ctx:
            ctx.prec=precision
            assert run(pair(0,0),pair(4,-4),equity='1000.96') == {
                PAIRS[0]:Decimal(4),PAIRS[1]:Decimal(-4)}
            assert run(pair(0,0),pair(0,0)) == {p:Decimal(0) for p in PAIRS}


def test_non_power_of_ten_lot_output_is_exact():
    with localcontext() as ctx:
        ctx.prec=6;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
        result=run(pair(0,0),pair('1.23456789','-1.23456789'),step=pair('.025','.03'))
    assert result=={PAIRS[0]:Decimal('1.225'),PAIRS[1]:Decimal('-1.23')}
