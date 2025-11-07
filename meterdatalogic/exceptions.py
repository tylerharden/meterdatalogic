class MDTError(Exception): ...


class CanonError(MDTError): ...


class CanonMultiSiteError(CanonError): ...


class PricingError(MDTError): ...


class IngestError(MDTError): ...


class TransformError(MDTError): ...


class ScenarioError(MDTError): ...


class TypesError(MDTError): ...


def require(condition: bool, message: str, exc: type[MDTError] = MDTError):
    """Raise the given exception if condition is False."""
    if not condition:
        raise exc(message)
