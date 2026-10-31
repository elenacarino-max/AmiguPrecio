"""Modelos validados para los calculos de precio."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PricingInput(BaseModel):
    """Datos que la artesana conoce y controla."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_name: str = Field(min_length=1, max_length=80)
    product_type: str = Field(min_length=1, max_length=80)
    materials_cost: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    hours_worked: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    hourly_rate: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    other_expenses: Decimal = Field(default=Decimal(0), ge=0, max_digits=10, decimal_places=2)
    margin_percent: Decimal = Field(ge=0, lt=100, max_digits=5, decimal_places=2)

    @field_validator(
        "materials_cost",
        "hours_worked",
        "hourly_rate",
        "other_expenses",
        "margin_percent",
    )
    @classmethod
    def reject_non_finite_numbers(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("El valor debe ser un numero finito")
        return value


class PricingResult(BaseModel):
    """Resultado auditable del calculo, expresado en euros."""

    labor_cost: Decimal
    production_cost: Decimal
    calculated_price: Decimal
    gross_profit: Decimal
    margin_percent: Decimal
