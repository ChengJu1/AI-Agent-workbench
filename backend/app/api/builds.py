"""Authoring jobs are server-backed; publication is a separate user action."""
from fastapi import APIRouter, BackgroundTasks, Depends
from app.api.dependencies import get_services
from app.models.api import AgentInfo
from app.models.builds import StartBuild, ReviseBuild, PublishBuild

router = APIRouter(prefix='/api/agent-builds')


@router.get('/runtime')
def runtime(services=Depends(get_services)):
    return services.agent_builds.sandbox.status()


@router.get('/packages')
def packages(services=Depends(get_services)):
    return services.agent_builds.store.packages()


@router.get('')
def list_builds(services=Depends(get_services)):
    return services.agent_builds.store.list_builds()


@router.post('', status_code=202)
def start(request: StartBuild, tasks: BackgroundTasks, services=Depends(get_services)):
    build, created = services.agent_builds.store.start(request)
    if created:
        tasks.add_task(services.agent_builds.process, build['id'], build['revision'])
    return build


@router.get('/{build_id}')
def get_build(build_id: str, services=Depends(get_services)):
    return services.agent_builds.store.get(build_id)


@router.post('/{build_id}/messages', status_code=202)
def revise(build_id: str, request: ReviseBuild, tasks: BackgroundTasks, services=Depends(get_services)):
    build = services.agent_builds.store.revise(build_id, request)
    tasks.add_task(services.agent_builds.process, build_id, build['revision'])
    return build


@router.post('/{build_id}/publish', status_code=201, response_model=AgentInfo)
def publish(build_id: str, request: PublishBuild, services=Depends(get_services)):
    return services.agent_builds.store.publish(build_id, request.expected_revision, request.approved_capabilities)
