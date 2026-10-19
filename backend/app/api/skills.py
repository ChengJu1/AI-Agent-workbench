from fastapi import APIRouter, Depends

from app.api.dependencies import get_services
from app.models.skills import SkillDefinition, SkillInfo, SkillImportPreview, SkillImportRequest, SkillUpdate
from app.services.skill_import import preview_skill


router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=list[SkillInfo])
def list_skills(services=Depends(get_services)):
    return services.skills.list()


@router.post("", response_model=SkillInfo, status_code=201)
def create_skill(request: SkillDefinition, services=Depends(get_services)):
    return services.skills.save(request)


@router.post("/import-preview", response_model=SkillImportPreview)
def import_preview(request: SkillImportRequest):
    return preview_skill(request)


@router.put("/{skill_id}", response_model=SkillInfo)
def update_skill(skill_id: str, request: SkillUpdate, services=Depends(get_services)):
    return services.skills.save(request, skill_id, request.expected_version)


@router.get("/{skill_id}/versions", response_model=list[SkillInfo])
def skill_versions(skill_id: str, services=Depends(get_services)):
    return services.skills.versions(skill_id)
