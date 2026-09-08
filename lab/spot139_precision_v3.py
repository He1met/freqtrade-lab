"""Ex-ante absolute rejection envelope for pinned native spot arithmetic.

Not an economic tolerance. Exact gross quantities/fees remain separately checked.
64 operations per historical-order iteration covers float conversions, spot fee
products, additions and wallet sums; native recalc revisits <= n squared items.
Use gamma(k)=k*u/(1-k*u), u=2^-53; eight-place profit rounding contributes
0.5e-8 per sell. CCXT average division truncates at 18 decimal places.
"""
from fractions import Fraction as F


def rejection_bound(n,sells,turnover,gross_units):
    k=64*n*n;u=F(1,2**53)
    if n<1 or k*u>=F(1,2):raise ValueError('unsupported operation count')
    gamma=k*u/(1-k*u)
    return sells*F(1,200000000)+gamma*(F(1000)+4*turnover)+n*gross_units*F(1,10**18)


def check_residual(observed,expected,bound):
    residual=F(str(observed))-expected
    if abs(residual)>bound:raise ValueError('ACCOUNTING_UNRESOLVED: native residual exceeds precision envelope')
    return residual
