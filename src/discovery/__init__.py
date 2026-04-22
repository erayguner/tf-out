from .models import DiscoveredResource, DiscoveryReport


# CloudAssetClient is imported lazily to keep google-cloud-asset optional for unit tests
def __getattr__(name):
    if name == "CloudAssetClient":
        from .cai_client import CloudAssetClient

        return CloudAssetClient
    raise AttributeError(name)


__all__ = ["CloudAssetClient", "DiscoveredResource", "DiscoveryReport"]
