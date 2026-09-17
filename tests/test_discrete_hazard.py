import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
from scipy.optimize import check_grad
from predictive_maintenance.core.records import FeatureRecord, TargetRecord
from predictive_maintenance.models.temporal.discrete_hazard import (
    DiscreteHazardRiskModel, HazardConfig, landmark_masks, logistic_objective,
)


def fixture():
    features,targets=[],[]
    for unit,end in [("a",8),("b",12),("c",10)]:
        for t in range(1,end):
            features.append(FeatureRecord(unit_id=unit,cycle=t,values={"age_cycle":float(t)}))
            targets.append(TargetRecord(unit_id=unit,cycle=t,values={"observed_end":end,"event_observed":1}))
    return features,targets


class DiscreteHazardTests(unittest.TestCase):
    def test_optimizer_failure_is_not_a_fitted_model(self):
        f,y=fixture(); m=DiscreteHazardRiskModel(["age_cycle"]).fit(f,y)
        with patch("predictive_maintenance.models.temporal.discrete_hazard.minimize",
                   return_value=SimpleNamespace(success=False,message="failed")):
            with self.assertRaises(RuntimeError): m.fit(f,y)
        with self.assertRaises(RuntimeError): m.predict_risk(f,horizon=2)

    def test_fit_with_synthetic_incomplete_followup(self):
        f,y=fixture()
        y=[TargetRecord(r.unit_id,r.cycle,{"observed_end":r.values["observed_end"],
            "event_observed":0 if r.unit_id=="b" else 1}) for r in y]
        model=DiscreteHazardRiskModel(["age_cycle"],HazardConfig(max_horizon=5)).fit(f,y)
        a,b=landmark_masks(f,y,5)
        self.assertEqual(model.training_summary["event_steps"],int(b.sum()))
        self.assertEqual(model.training_summary["landmark_steps"],int(a.sum()))
        self.assertTrue(np.isfinite(model.predict_hazards(f,horizon=5)).all())

    def test_nonfinite_hazard_returns_unavailable(self):
        f,y=fixture(); m=DiscreteHazardRiskModel(["age_cycle"]).fit(f,y)
        m.theta[-1]=np.nan
        p=m.predict_risk(f[:1],horizon=2)[0]
        self.assertEqual(p.prediction_status,"unavailable")
        self.assertIsNone(p.risk_score)

    def test_landmark_event_step_and_no_unit_mixing(self):
        f,y=fixture()
        a,b=landmark_masks(f,y,5)
        for j,(origin,outcome) in enumerate(zip(f,y)):
            remaining=outcome.values["observed_end"]-origin.cycle
            np.testing.assert_array_equal(a[j],np.arange(1,6)<=remaining)
            np.testing.assert_array_equal(b[j],np.arange(1,6)==remaining)
        with self.assertRaises(ValueError):
            landmark_masks(f,y[::-1],5)
        with self.assertRaises(ValueError):
            landmark_masks(f+f[:1],y+y[:1],5)

    def test_synthetic_censoring_masks_unknown_steps(self):
        f=[FeatureRecord(unit_id="a",cycle=3,values={"age_cycle":3.})]
        y=[TargetRecord(unit_id="a",cycle=3,values={"observed_end":5,"event_observed":0})]
        a,b=landmark_masks(f,y,5)
        np.testing.assert_array_equal(a,[[True,True,False,False,False]])
        self.assertEqual(b.sum(),0)
        f=[FeatureRecord(unit_id="a",cycle=5,values={"age_cycle":5.})]
        y=[TargetRecord(unit_id="a",cycle=5,values={"observed_end":5,"event_observed":0})]
        self.assertFalse(landmark_masks(f,y,5)[0].any())
        y=[TargetRecord(unit_id="a",cycle=5,values={"observed_end":5,"event_observed":1})]
        with self.assertRaises(ValueError): landmark_masks(f,y,5)

    def test_factored_loss_matches_expansion_and_gradient(self):
        f,y=fixture(); a,b=landmark_masks(f,y,5)
        z=np.array([[r.cycle/10] for r in f]); k=np.arange(1,6)/5
        theta=np.array([.3,.8,-2.])
        loss,gradient=logistic_objective(theta,z,k,a,b,1.)
        expanded=np.array([[z[i,0],k[j],1.] for i,j in zip(*np.where(a))])
        labels=b[a]; logits=expanded@theta
        reference=np.sum(np.logaddexp(0,logits)-labels*logits)+.5*np.dot(theta[:-1],theta[:-1])
        self.assertAlmostEqual(loss,reference)
        error=check_grad(lambda w:logistic_objective(w,z,k,a,b,1.)[0],
                         lambda w:logistic_objective(w,z,k,a,b,1.)[1],theta)
        self.assertLess(error,1e-5)
        altered=b.copy(); altered[~a]=True
        self.assertAlmostEqual(loss,logistic_objective(theta,z,k,a,altered,1.)[0])

    def test_bounds_and_horizon_coherence(self):
        f,y=fixture(); m=DiscreteHazardRiskModel(["age_cycle"],HazardConfig(max_horizon=5)).fit(f,y)
        h=m.predict_hazards(f,horizon=5); s=np.cumprod(1-h,axis=1)
        self.assertTrue(((h>=0)&(h<=1)).all())
        self.assertTrue(((s>=0)&(s<=1)).all())
        self.assertTrue((np.diff(s,axis=1)<=0).all())
        self.assertTrue((np.diff(1-s,axis=1)>=0).all())
        for short,long in zip(m.predict_risk(f,horizon=2),m.predict_risk(f,horizon=5)):
            self.assertLessEqual(short.risk_score,long.risk_score)
            self.assertEqual(short.horizon,2)
            self.assertEqual(short.prediction_status,"available")
        np.testing.assert_array_equal(h[:,:2],m.predict_hazards(f,horizon=2))

    def test_save_load_and_reproducibility(self):
        f,y=fixture(); config=HazardConfig(max_horizon=5)
        m=DiscreteHazardRiskModel(["age_cycle"],config).fit(f,y)
        other=DiscreteHazardRiskModel(["age_cycle"],config).fit(f,y)
        np.testing.assert_allclose(m.theta,other.theta,atol=1e-12)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"model.joblib"; m.save(path)
            loaded=DiscreteHazardRiskModel.load(path)
            self.assertEqual(loaded.config,config)
            self.assertEqual(loaded.predict_risk(f,horizon=5),m.predict_risk(f,horizon=5))

    def test_invalid_input_explicit_status_and_forbidden_features(self):
        f,y=fixture(); m=DiscreteHazardRiskModel(["age_cycle"],HazardConfig(max_horizon=5)).fit(f,y)
        for values in [{},{"age_cycle":float("nan")},{"age_cycle":100.}]:
            bad=FeatureRecord(unit_id="a",cycle=1,values=values)
            p=m.predict_risk([bad],horizon=3)[0]
            self.assertEqual((p.prediction_status,p.input_validity),("unavailable","invalid"))
            self.assertIsNone(p.risk_score)
            self.assertEqual(p.unit_id,"a")
        self.assertEqual(m.predict_risk(f[:1],horizon=6)[0].prediction_status,"unavailable")
        for name in ["RUL","normalized_life","future_sensor","RUL__current","observed_end","sensor_at_future"]:
            with self.assertRaises(ValueError): DiscreteHazardRiskModel(["age_cycle",name])
        self.assertEqual(m.predict_risk([],horizon=3),[])
