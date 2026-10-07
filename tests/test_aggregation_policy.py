from weavehr_yaib.aggregation import uses_ricu_aggregation


def test_native_ricu_dataset_uses_ricu_aggregation() -> None:
    assert uses_ricu_aggregation("mimic-iv")


def test_nwicu_uses_ricu_aggregation_without_native_ricu_support() -> None:
    assert uses_ricu_aggregation("nwicu")


def test_mimic_iv_demo_uses_ricu_aggregation_without_comparison() -> None:
    assert uses_ricu_aggregation("mimic-iv-demo")


def test_unknown_dataset_falls_back_to_mean() -> None:
    assert not uses_ricu_aggregation("unknown-dataset")
