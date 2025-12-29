from pydantic import BaseModel


class ArticlePlanningSettingsBase(BaseModel):
    article_id: int
    include_in_planning: bool = True
    priority: int = 0
    target_coverage_days: int | None = None
    lead_time_days: int | None = None
    service_level_percent: int | None = None


class ArticlePlanningSettingsCreate(ArticlePlanningSettingsBase):
    pass


class ArticlePlanningSettingsUpdate(BaseModel):
    include_in_planning: bool | None = None
    priority: int | None = None
    target_coverage_days: int | None = None
    lead_time_days: int | None = None
    service_level_percent: int | None = None


class ArticlePlanningSettingsRead(ArticlePlanningSettingsBase):
    id: int

    class Config:
        orm_mode = True


class ColorPlanningSettingsBase(BaseModel):
    article_id: int
    color_id: int
    fabric_min_batch_qty: int | None = None


class ColorPlanningSettingsCreate(ColorPlanningSettingsBase):
    pass


class ColorPlanningSettingsUpdate(BaseModel):
    fabric_min_batch_qty: int | None = None


class ColorPlanningSettingsRead(ColorPlanningSettingsBase):
    id: int

    class Config:
        orm_mode = True


class ElasticTypeBase(BaseModel):
    code: str
    name: str


class ElasticTypeCreate(ElasticTypeBase):
    pass


class ElasticTypeUpdate(BaseModel):
    code: str | None = None
    name: str | None = None


class ElasticTypeRead(ElasticTypeBase):
    id: int

    class Config:
        orm_mode = True


class ElasticPlanningSettingsBase(BaseModel):
    article_id: int
    elastic_type_id: int
    elastic_min_batch_qty: int | None = None


class ElasticPlanningSettingsCreate(ElasticPlanningSettingsBase):
    pass


class ElasticPlanningSettingsUpdate(BaseModel):
    elastic_min_batch_qty: int | None = None


class ElasticPlanningSettingsRead(ElasticPlanningSettingsBase):
    id: int

    class Config:
        orm_mode = True


class GlobalPlanningSettingsBase(BaseModel):
    default_target_coverage_days: int = 60
    default_lead_time_days: int = 70
    default_service_level_percent: int = 90
    default_fabric_min_batch_qty: int = 7000
    default_elastic_min_batch_qty: int = 3000


class GlobalPlanningSettingsCreate(GlobalPlanningSettingsBase):
    pass


class GlobalPlanningSettingsUpdate(BaseModel):
    default_target_coverage_days: int | None = None
    default_lead_time_days: int | None = None
    default_service_level_percent: int | None = None
    default_fabric_min_batch_qty: int | None = None
    default_elastic_min_batch_qty: int | None = None


class GlobalPlanningSettingsRead(GlobalPlanningSettingsBase):
    id: int

    class Config:
        orm_mode = True


class PlanningSettingsBase(BaseModel):
    article_id: int
    is_active: bool = True
    min_fabric_batch: int
    min_elastic_batch: int
    alert_threshold_days: int
    safety_stock_days: int
    strictness: float
    notes: str | None = None


class PlanningSettingsCreate(PlanningSettingsBase):
    pass


class PlanningSettingsUpdate(BaseModel):
    article_id: int | None = None
    is_active: bool | None = None
    min_fabric_batch: int | None = None
    min_elastic_batch: int | None = None
    alert_threshold_days: int | None = None
    safety_stock_days: int | None = None
    strictness: float | None = None
    notes: str | None = None


class PlanningSettingsRead(PlanningSettingsBase):
    id: int

    class Config:
        orm_mode = True


class ArticlePlanningSettingsExperimentalSnapshot(BaseModel):
    include_in_planning: bool | None = None
    priority: int | None = None
    lead_time_days: int | None = None
    service_level_percent: int | None = None


class ArticlePlanningSettingsSnapshot(BaseModel):
    target_coverage_days: int | None = None
    experimental: ArticlePlanningSettingsExperimentalSnapshot | None = None


class PlanningSettingsExperimentalSnapshot(BaseModel):
    alert_threshold_days: int | None = None
    safety_stock_days: int | None = None
    notes: str | None = None


class PlanningSettingsSnapshot(BaseModel):
    is_active: bool
    min_fabric_batch: int
    min_elastic_batch: int
    strictness: float
    experimental: PlanningSettingsExperimentalSnapshot | None = None


class ColorPlanningSettingsSnapshot(BaseModel):
    color_id: int
    fabric_min_batch_qty: int | None = None


class ElasticPlanningSettingsSnapshot(BaseModel):
    elastic_type_id: int
    elastic_type_name: str
    elastic_min_batch_qty: int | None = None


class GlobalPlanningSettingsExperimentalSnapshot(BaseModel):
    default_lead_time_days: int | None = None
    default_service_level_percent: int | None = None
    default_fabric_min_batch_qty: int | None = None
    default_elastic_min_batch_qty: int | None = None


class GlobalPlanningSettingsSnapshot(BaseModel):
    default_target_coverage_days: int | None = None
    experimental: GlobalPlanningSettingsExperimentalSnapshot | None = None


class ArticlePlanningConfigSnapshot(BaseModel):
    article_id: int
    article_code: str
    article_planning_settings: ArticlePlanningSettingsSnapshot | None = None
    planning_settings: PlanningSettingsSnapshot | None = None
    color_settings: list[ColorPlanningSettingsSnapshot] = []
    elastic_settings: list[ElasticPlanningSettingsSnapshot] = []


class PlanningConfigSnapshotResponse(BaseModel):
    global_settings: GlobalPlanningSettingsSnapshot | None = None
    articles: list[ArticlePlanningConfigSnapshot]
