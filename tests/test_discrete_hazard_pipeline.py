import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from test_classical_ml_pipeline import _frame
from predictive_maintenance.application.discrete_hazard_fd001 import run_discrete_hazard, sha
from predictive_maintenance.application.classical_ml_fd001 import _feature_records
from predictive_maintenance.features.causal import CausalTelemetryFeatures, CausalFeatureConfig
from predictive_maintenance.models.temporal.discrete_hazard import landmark_masks
from predictive_maintenance.core.records import TargetRecord


class HazardPipelineTests(unittest.TestCase):
    def test_retrospective_raw_column_rejected_before_transform(self):
        frame=_frame({1:12,2:14})
        frame["RUL"]=0
        with self.assertRaises(ValueError):
            CausalTelemetryFeatures().fit_frame(frame)

    def test_prefix_features_frozen_in_landmarks(self):
        frame=_frame({1:12,2:14})
        engineer=CausalTelemetryFeatures(CausalFeatureConfig(windows=(2,3))).fit_frame(frame)
        original=engineer.transform_frame(frame)
        altered=frame.copy()
        altered.loc[(altered.unit_id==1)&(altered.cycle>6),"sensor_2"] += 100000
        transformed=engineer.transform_frame(altered)
        prefix=(frame.unit_id==1)&(frame.cycle<=6)
        pd.testing.assert_frame_equal(original.loc[prefix],transformed.loc[prefix])
        pd.testing.assert_frame_equal(original.loc[frame.unit_id==2],transformed.loc[frame.unit_id==2])
        records=_feature_records(original.loc[prefix],engineer.feature_names)
        outcomes=[TargetRecord(f.unit_id,f.cycle,{"observed_end":12,"event_observed":1}) for f in records]
        before=[dict(f.values) for f in records]
        landmark_masks(records,outcomes,5)
        self.assertEqual(before,[dict(f.values) for f in records])

    def test_pipeline_isolation_oof_and_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); data=root/"data"; data.mkdir(); reports=root/"reports"
            train=_frame({1:14,2:16,3:18,4:20}); val=_frame({5:17,6:19})
            train.to_parquet(data/"train.parquet"); val.to_parquet(data/"validation.parquet")
            (data/"test_internal.parquet").write_text("DO NOT READ")
            (data/"split_manifest.json").write_text(json.dumps({"dataset":"FD001",
                "source":{"file":"train_FD001.txt"},"units":{"train":[1,2,3,4],"validation":[5,6],"test_internal":[7]},
                "rows":{"train":len(train),"validation":len(val),"test_internal":1}}))
            config=root/"config.toml"
            config.write_text('[model]\nmax_horizon=5\n[features]\nwindows=[2,3]\n[cross_validation]\nfolds=2\nseed=4302\n[evaluation]\nhorizons=[2,5]\nage_bin_width=5\n')
            with patch("pandas.read_parquet",wraps=pd.read_parquet) as read:
                result=run_discrete_hazard(data,config,reports,compare=False)
            self.assertEqual([c.args[0].name for c in read.call_args_list],["train.parquet","validation.parquet"])
            a=reports/"discrete_hazard/artifacts"
            oof=pd.read_parquet(a/"train_oof_predictions.parquet")
            self.assertEqual(len(oof),(len(train)-4)*2)
            self.assertFalse(oof.duplicated(["unit_id","cycle","horizon"]).any())
            folds=json.loads((a/"fold_manifest.json").read_text())
            for fold in folds:
                self.assertFalse(set(fold["fitting_units"])&set(fold["holdout_units"]))
                self.assertEqual(set(oof.loc[oof.fold==fold["fold"],"unit_id"]),set(fold["holdout_units"]))
                saved=CausalTelemetryFeatures.load(a/f'fold_{fold["fold"]}_features.json')
                fitting=train.loc[train.unit_id.isin(fold["fitting_units"])].reset_index(drop=True)
                mask=(fitting.cycle<fitting.groupby("unit_id").cycle.transform("max")).to_numpy()
                expected=CausalTelemetryFeatures(CausalFeatureConfig(windows=(2,3))).fit_frame(fitting,fit_mask=mask)
                self.assertEqual(saved.imputation_medians,expected.imputation_medians)
            card=json.loads((reports/"discrete_hazard/model_card.json").read_text(encoding="utf-8"))
            self.assertEqual(card["artifact_hash"],sha(a/"model.joblib"))
            self.assertEqual(result["coherence"]["validation"]["violations"],0)
            self.assertTrue((a/"calibration_by_age.parquet").exists())
