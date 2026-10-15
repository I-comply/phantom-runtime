from datetime import datetime
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel, Field

class AssetCategory(str, Enum):
    SOFTWARE_SAAS = "software_saas"
    BACKEND_MODULE = "backend_module"
    FRONTEND_COMPONENT = "frontend_component"
    DATABASE_SCHEMA = "database_schema"
    PROMPT_WORKFLOW = "prompt_workflow"

class AssetPackageRequest(BaseModel):
    asset_name: str = Field(..., min_length=3, max_length=100)
    category: AssetCategory
    description: str = Field(..., min_length=10)
    source_code: str = Field(..., min_length=1)

class AssetPackageResponse(BaseModel):
    package_id: str
    asset_name: str
    category: AssetCategory
    marketing_copy: str
    legal_documents: Dict[str, str]
    optimal_marketplaces: List[str]
    status: str
    created_at: datetime
