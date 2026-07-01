class NonCriticalDataSourceError(Exception):
    """Raised when a partial data source failure should not abort the pipeline."""


class PublishError(Exception):
    """Raised when downstream publishing fails."""


class FatalPipelineError(Exception):
    """Raised when the pipeline cannot proceed and should stop."""
