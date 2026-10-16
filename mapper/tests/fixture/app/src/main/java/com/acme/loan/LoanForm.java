package com.acme.loan;

import org.apache.struts.action.*;

public class LoanForm extends ActionForm {
    private String amount;
    private String globalAccountNum;
    public String getAmount() { return amount; }
    public String getGlobalAccountNum() { return globalAccountNum; }
    public ActionErrors validate(ActionMapping mapping, Object request) {
        ActionErrors errors = new ActionErrors();
        if (amount == null || amount.isEmpty()) {
            errors.add(LoanConstants.AMOUNT_REQUIRED, new ActionMessage(LoanConstants.AMOUNT_REQUIRED));
        }
        return errors;
    }
}
