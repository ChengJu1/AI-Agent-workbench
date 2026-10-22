from fastapi import APIRouter, Depends
from app.api.dependencies import get_services
from app.models.tracking import TrackingDefinition, TrackingControl, TrackingEdit, WorkItemSave
from pydantic import Field

router = APIRouter(prefix='/api')


@router.get('/work-items')
def work_items(agent_id: str | None = None, services=Depends(get_services)):
    return services.tracking.items.list(agent_id)


@router.get('/work-items/{item_id}')
def work_item(item_id: str, services=Depends(get_services)):
    return services.tracking.items.get(item_id)


class SaveWorkItem(WorkItemSave):
    conversation_id: str = Field(min_length=1, max_length=100)


@router.post('/work-items')
def save_work_item(request: SaveWorkItem, services=Depends(get_services)):
    agent = services.platform.require(request.conversation_id, 'tracking')
    definition = WorkItemSave.model_validate(request.model_dump(exclude={'conversation_id'}))
    return services.tracking.items.save(request.conversation_id, agent.id, definition)


@router.get('/execution-records')
def records(agent_id: str | None = None, services=Depends(get_services)):
    return services.tracking.store.records(agent_id)


@router.get('/execution-records/{record_id}')
def record(record_id: str, services=Depends(get_services)):
    return services.tracking.store.record(record_id)


@router.get('/tracking')
def tasks(agent_id: str | None = None, services=Depends(get_services)):
    return services.tracking.store.tasks(agent_id)


class NewTracking(TrackingDefinition):
    conversation_id: str = Field(min_length=1, max_length=100)


@router.post('/tracking', status_code=201)
def create(request: NewTracking, services=Depends(get_services)):
    return services.tracking.create(request.conversation_id, TrackingDefinition.model_validate(request.model_dump(exclude={'conversation_id'})))


@router.get('/tracking/{task_id}')
def get_task(task_id: str, services=Depends(get_services)):
    return services.tracking.store.get(task_id)


@router.put('/tracking/{task_id}')
def edit(task_id: str, request: TrackingEdit, services=Depends(get_services)):
    task = services.tracking.store.get(task_id)
    definition = TrackingDefinition.model_validate(request.model_dump(exclude={'expected_revision'}))
    services.tracking.validate(task['conversation_id'], definition)
    return services.tracking.store.edit(task_id, definition, request.expected_revision)


@router.post('/tracking/{task_id}/control')
def control(task_id: str, request: TrackingControl, services=Depends(get_services)):
    task = services.tracking.store.get(task_id)
    if request.action == 'resume':
        services.tracking.validate(task['conversation_id'], TrackingDefinition.model_validate(task['definition']))
    return services.tracking.store.control(task_id, request)


@router.post('/tracking/{task_id}/check')
def check(task_id: str, services=Depends(get_services)):
    services.tracking.store.get(task_id)
    return services.tracking.check(task_id)
