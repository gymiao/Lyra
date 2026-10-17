from personal_quant.options.capabilities import describe


def test_template_name_and_rule_do_not_grant_engine_source_or_account_permission():
    result=describe('iron_condor',None,None)
    assert result['scenario']=='SUPPORTED' and result['monthly_selection']=='SUPPORTED'
    assert result['simulated_plan_preconditions']=='BLOCKED'
    assert result['checks']==['ENGINE_EVIDENCE_REQUIRED','INPUT_PACKAGE_REQUIRED']
    assert not result['executable'] and result['broker_permissions']=='UNVERIFIED' and result['financial_events_added']==0
