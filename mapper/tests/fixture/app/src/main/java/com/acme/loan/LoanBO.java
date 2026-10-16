package com.acme.loan;

import java.util.Set;

public class LoanBO {
    private int state;
    private Set<PaymentEntity> payments;

    public Set<PaymentEntity> getPayments() { return payments; }
    public void setState(int s) { this.state = s; }

    public PaymentEntity disburse(String amount) {
        if (state != 3) {
            throw new LoanException(LoanConstants.NOT_APPROVED);
        }
        setState(5);
        PaymentEntity p = new PaymentEntity(amount);
        payments.add(p);
        return p;
    }
}
