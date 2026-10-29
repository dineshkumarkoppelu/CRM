"""Built-in domains and their descriptions.

The 5 built-in domains are always present (created by app/schema/init.cypher) and come first,
in this order, everywhere including the UI. Managers can add more domains at runtime
(POST /api/domains); those are ordered after the built-ins by creation. The live, ordered list
of all domains comes from `services/domain_service.domain_names()`.

`BUILTIN_DOMAINS` is also what the synthetic data generator uses.
"""

from __future__ import annotations

BUILTIN_DOMAINS: tuple[str, ...] = ("AI", "Cybersecurity", "IoT", "DevOps", "Cloud Migration")

# Kept for the generator, profiles and tests, which are about the planted built-in data.
DOMAINS = BUILTIN_DOMAINS

# Used for the embeddings (text = "<name>: <description>"). Changing a description means
# regenerating app/core/domain_embeddings.json with scripts/embed_builtin_domains.py.
BUILTIN_DESCRIPTIONS: dict[str, str] = {
    "AI": (
        "Artificial intelligence and machine learning: predictive models, natural language "
        "processing, computer vision and data science solutions."
    ),
    "Cybersecurity": (
        "Protecting networks, endpoints and identities: threat detection, SOC monitoring, "
        "vulnerability management, security audits and compliance."
    ),
    "IoT": (
        "Internet of Things: connected devices, sensors, telemetry and edge hardware for "
        "factories, fleets and utilities."
    ),
    "DevOps": (
        "CI/CD pipelines, containers and Kubernetes, infrastructure as code, observability and "
        "release automation."
    ),
    "Cloud Migration": (
        "Moving applications, data and infrastructure to public or hybrid cloud platforms such "
        "as AWS and Azure, including re-platforming and cost optimisation."
    ),
}

assert set(BUILTIN_DESCRIPTIONS) == set(BUILTIN_DOMAINS)


def embedding_text(name: str, description: str) -> str:
    """The text that is embedded for a domain."""
    return f"{name}: {description.strip()}"
