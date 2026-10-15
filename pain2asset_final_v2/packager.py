import hashlib
from datetime import datetime, timezone
from typing import List
from models import AssetPackageRequest, AssetPackageResponse, AssetCategory
from legal import LegalComplianceGenerator

class AssetPackagerEngine:
    def package_asset(self, req: AssetPackageRequest) -> AssetPackageResponse:
        pkg_id = f"pkg_{hashlib.sha256((req.asset_name + req.description).encode('utf-8')).hexdigest()[:12]}"

        marketing_copy = (
            f"# {req.asset_name}\n\n"
            f"**Eliminate persistent developer friction with a production-grade solution.**\n\n"
            f"{req.description}\n\n"
            f"### Technical Highlights\n"
            f"- Production-oriented code.\n"
            f"- Embedded privacy and legal compliance documents.\n"
        )

        legal_docs = {
            "privacy_policy": LegalComplianceGenerator.generate_privacy_policy(),
            "terms_of_service": LegalComplianceGenerator.generate_terms_of_service(),
        }

        return AssetPackageResponse(
            package_id=pkg_id,
            asset_name=req.asset_name,
            category=req.category,
            marketing_copy=marketing_copy,
            legal_documents=legal_docs,
            optimal_marketplaces=self._match_marketplaces(req.category),
            status="packaged_ready",
            created_at=datetime.now(timezone.utc),
        )

    def _match_marketplaces(self, category: AssetCategory) -> List[str]:
        mapping = {
            AssetCategory.SOFTWARE_SAAS: ["LemonSqueezy", "Gumroad", "ProductHunt"],
            AssetCategory.BACKEND_MODULE: ["GitHub Sponsors", "RapidAPI", "Gumroad"],
            AssetCategory.FRONTEND_COMPONENT: ["ThemeForest", "Gumroad", "Codepen Pro"],
            AssetCategory.DATABASE_SCHEMA: ["Supabase Marketplace", "GitHub", "Gumroad"],
            AssetCategory.PROMPT_WORKFLOW: ["PromptBase", "Gumroad", "FlowGPT"],
        }
        return mapping.get(category, ["Gumroad", "GitHub"])
