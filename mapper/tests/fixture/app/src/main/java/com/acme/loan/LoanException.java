package com.acme.loan;
public class LoanException extends RuntimeException {
    public LoanException(String key) { super(key); }
}
