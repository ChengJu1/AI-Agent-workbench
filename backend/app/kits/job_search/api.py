"""Application ledger and profile API. Nothing here reaches an employer's site."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from app.api.dependencies import get_services
from app.errors import ServiceError
from app.kits.job_search.models import ApplicationSave, KitEdit, StageChange
from app.kits.job_search.profiles import ProfileSave
from app.kits.job_search.calendar import build_calendar
from app.kits.job_search.brief import build_brief

router = APIRouter(prefix='/api')


def job_kit(services=Depends(get_services)):
    return services.kits['applications']


@router.get('/applications')
def list_applications(kit=Depends(job_kit)):
    return kit.applications.list()


@router.get('/brief')
def brief(kit=Depends(job_kit)):
    return build_brief(kit.applications.list(), kit.applications.database)


@router.get('/applications/calendar.ics')
def calendar(kit=Depends(job_kit)):
    body = build_calendar(kit.applications.list())
    return Response(body, media_type='text/calendar; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="workbench-applications.ics"'})


@router.post('/applications', status_code=201)
def create_application(request: ApplicationSave, kit=Depends(job_kit)):
    return kit.applications.save(request)


@router.get('/applications/{application_id}')
def get_application(application_id: str, kit=Depends(job_kit)):
    return kit.applications.get(application_id)


@router.put('/applications/{application_id}')
def update_application(application_id: str, request: ApplicationSave, kit=Depends(job_kit)):
    if request.expected_revision is None:
        raise ServiceError('修改台账需要提供当前版本。', 422)
    return kit.applications.save(request, application_id)


@router.post('/applications/{application_id}/stage')
def change_stage(application_id: str, request: StageChange, kit=Depends(job_kit)):
    return kit.applications.change_stage(application_id, request)


@router.post('/applications/{application_id}/kit')
def edit_kit(application_id: str, request: KitEdit, kit=Depends(job_kit)):
    return kit.applications.edit_kit(application_id, request)


@router.delete('/applications/{application_id}')
def delete_application(application_id: str, kit=Depends(job_kit)):
    return kit.applications.delete(application_id)


@router.get('/profiles')
def profiles(kit=Depends(job_kit)):
    return kit.profiles.list()


@router.post('/profiles', status_code=201)
def create_profile(request: ProfileSave, kit=Depends(job_kit)):
    return kit.profiles.save(request)


@router.get('/profiles/{profile_id}')
def get_profile(profile_id: str, version: int | None = Query(default=None, ge=1), kit=Depends(job_kit)):
    return kit.profiles.get(profile_id, version)


@router.post('/profiles/{profile_id}/versions', status_code=201)
def save_profile(profile_id: str, request: ProfileSave, kit=Depends(job_kit)):
    return kit.profiles.save(request, profile_id)


@router.delete('/profiles/{profile_id}')
def delete_profile(profile_id: str, kit=Depends(job_kit)):
    return kit.profiles.delete(profile_id)
