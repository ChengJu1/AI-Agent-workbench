"""Application ledger and profile API. Nothing here reaches an employer's site."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from app.api.dependencies import get_services
from app.errors import ServiceError
from app.models.applications import ApplicationSave, KitEdit, StageChange
from app.models.profiles import ProfileSave
from app.services.calendar_export import build_calendar
from app.services.daily_brief import build_brief

router = APIRouter(prefix='/api')


@router.get('/applications')
def list_applications(services=Depends(get_services)):
    return services.applications.list()


@router.get('/brief')
def brief(services=Depends(get_services)):
    return build_brief(services.applications.list(), services.applications.database)


@router.get('/applications/calendar.ics')
def calendar(services=Depends(get_services)):
    body = build_calendar(services.applications.list())
    return Response(body, media_type='text/calendar; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="workbench-applications.ics"'})


@router.post('/applications', status_code=201)
def create_application(request: ApplicationSave, services=Depends(get_services)):
    return services.applications.save(request)


@router.get('/applications/{application_id}')
def get_application(application_id: str, services=Depends(get_services)):
    return services.applications.get(application_id)


@router.put('/applications/{application_id}')
def update_application(application_id: str, request: ApplicationSave, services=Depends(get_services)):
    if request.expected_revision is None:
        raise ServiceError('修改台账需要提供当前版本。', 422)
    return services.applications.save(request, application_id)


@router.post('/applications/{application_id}/stage')
def change_stage(application_id: str, request: StageChange, services=Depends(get_services)):
    return services.applications.change_stage(application_id, request)


@router.post('/applications/{application_id}/kit')
def edit_kit(application_id: str, request: KitEdit, services=Depends(get_services)):
    return services.applications.edit_kit(application_id, request)


@router.delete('/applications/{application_id}')
def delete_application(application_id: str, services=Depends(get_services)):
    return services.applications.delete(application_id)


@router.get('/profiles')
def profiles(services=Depends(get_services)):
    return services.profiles.list()


@router.post('/profiles', status_code=201)
def create_profile(request: ProfileSave, services=Depends(get_services)):
    return services.profiles.save(request)


@router.get('/profiles/{profile_id}')
def get_profile(profile_id: str, version: int | None = Query(default=None, ge=1), services=Depends(get_services)):
    return services.profiles.get(profile_id, version)


@router.post('/profiles/{profile_id}/versions', status_code=201)
def save_profile(profile_id: str, request: ProfileSave, services=Depends(get_services)):
    return services.profiles.save(request, profile_id)


@router.delete('/profiles/{profile_id}')
def delete_profile(profile_id: str, services=Depends(get_services)):
    return services.profiles.delete(profile_id)
