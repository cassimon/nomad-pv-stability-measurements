import re


def shown(quantity) -> str:
    """A quantity the way a person reads it: a temperature in °C, a fraction in %, a
    time in the largest of h, min and s that counts it whole."""
    if quantity.check('[temperature]'):
        quantity = quantity.to('degC')
    elif quantity.check('[time]'):
        seconds = quantity.to('s').magnitude
        for unit, size in (('h', 3600), ('min', 60)):
            if seconds >= size and float(seconds / size).is_integer():
                return f'{seconds / size:.4g} {unit}'
        return f'{seconds:.4g} s'
    elif quantity.dimensionless:
        quantity = quantity.to('percent')
    return f'{quantity.magnitude:.4g} {quantity.units:~P}'


def words(class_name: str) -> str:
    """`HoldRelativeHumidity` as `Hold relative humidity`; acronyms stay: `MPP tracking`."""
    parts = re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+', class_name)
    text = ' '.join(part if part.isupper() else part.lower() for part in parts)
    return text[:1].upper() + text[1:]
