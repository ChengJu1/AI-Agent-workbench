"""题集导出与知识库只读批量检索评估。"""
from fastapi import APIRouter, Depends

from app.api.dependencies import get_services
from app.models.evaluation import RetrievalReport, RetrievalSuite
from app.services.retrieval_evaluation import sample_suite


router = APIRouter(prefix="/api/knowledge-evaluations")


@router.get("/sample-suite", response_model=RetrievalSuite)
def get_sample_suite():
    return sample_suite()


@router.post("/{base_id}/run", response_model=RetrievalReport)
def evaluate(base_id: str, suite: RetrievalSuite, services=Depends(get_services)):
    return services.retrieval_evaluation.run(base_id, suite)
