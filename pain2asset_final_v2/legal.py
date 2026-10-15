from datetime import datetime, timezone

class LegalComplianceGenerator:
    @staticmethod
    def generate_privacy_policy(company_name: str = "Pain2Asset Forge") -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return (
            f"# Privacy Policy\n\n"
            f"**Effective Date:** {date_str} | **Entity:** {company_name}\n\n"
            f"1. **Information Collection:** We collect telemetry strictly to compile software solution bundles.\n"
            f"2. **Intellectual Property Protection:** Source code and user assets are never retained for public model training.\n"
            f"3. **Data Security:** Persistent records are stored in a local SQLite database.\n"
            f"4. **User Control:** Users hold 100% ownership rights over all generated code artifacts.\n"
        )

    @staticmethod
    def generate_terms_of_service(company_name: str = "Pain2Asset Forge") -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return (
            f"# Terms of Service\n\n"
            f"**Effective Date:** {date_str} | **Entity:** {company_name}\n\n"
            f"1. **Acceptable Use:** Users agree not to deploy generated software for malicious operations.\n"
            f"2. **Ownership Rights:** All compiled outputs become the sole property of the generating user.\n"
            f"3. **Warranty Disclaimer:** Software is provided 'as-is' without express or implied warranty.\n"
        )
