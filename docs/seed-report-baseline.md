# Seed conversion report — `acceptance_dbunit.xml`

_Baseline run: generated against `base-schema.sql` (pre-Liquibase) in MariaDB 10.11; loaded with 0 errors; 27 loans across 5 states. Rerun `legacy/seed.sh` against the live HEAD schema._

- Business tables (DELETE+INSERT): 141
- Reference tables (INSERT IGNORE): 66
- Skipped bookkeeping tables: 35
- Dataset tables absent from target schema: 8

## Tables absent from target
- acc_financialyear (1 rows)
- activity_restriction_type (1 rows)
- config_key_value (18 rows)
- penalty_category (2 rows)
- penalty_formula (4 rows)
- penalty_frequency (4 rows)
- penalty_period (3 rows)
- penalty_status (2 rows)

## Dropped columns (in dataset, not in target)
- `customer_schedule`: last_updated
- `loan_fee_schedule`: last_updated
- `loan_offering`: fixed_repayment_flag
- `loan_schedule`: last_updated
- `question_group`: activity_id

## Defaulted NOT NULL columns (in target, not in dataset) — review
- `customer_picture`: customer_id

## Business tables
account (70), account_activity (0), account_custom_field (0), account_fees (13), account_flag_detail (0), account_notes (26), account_payment (15), account_status_change_history (71), account_trxn (18), admin_document (0), admin_document_acc_state_mix (0), attendance (0), branch_ho_update (0), calculated_interest_on_payment (0), cash_flow (0), cash_flow_detail (0), change_log (106), change_log_detail (115), checklist (0), checklist_detail (0), client_initial_savings_offering (0), client_perf_history (22), coa (56), coa_idmapper (0), coahierarchy (56), cust_perf_history (0), custom_field_definition (0), customer (40), customer_account (40), customer_account_activity (0), customer_address_detail (40), customer_attendance (0), customer_checklist (0), customer_custom_field (0), customer_detail (22), customer_family_detail (0), customer_fee_schedule (0), customer_flag_detail (0), customer_hierarchy (21), customer_historical_data (0), customer_loan_account_detail (0), customer_meeting (40), customer_meeting_detail (0), customer_movement (0), customer_name_detail (44), customer_note (31), customer_picture (22), customer_position (0), customer_program (0), customer_schedule (441), customer_trxn_detail (0), fee_frequency (5), fee_trxn_detail (3), feelevel (0), fees (5), financial_trxn (36), freq_of_deposits (0), gl_code (56), group_loan_counter (1), group_perf_history (10), holiday (0), imported_transactions_files (0), inherited_meeting (0), insurance_offering (0), loan_account (27), loan_activity_details (25), loan_amount_from_last_loan (0), loan_amount_from_loan_cycle (0), loan_amount_same_for_all_loan (15), loan_arrears_aging (0), loan_cash_flow (0), loan_counter (7), loan_fee_schedule (23), loan_offering (15), loan_offering_fund (15), loan_penalty (0), loan_perf_history (27), loan_schedule (229), loan_summary (27), loan_trxn_detail (17), max_min_interest_rate (27), max_min_loan_amount (27), max_min_no_of_install (27), meeting (74), monthly_cash_flow_details (0), no_of_install_from_last_loan (0), no_of_install_from_loan_cycle (0), no_of_install_same_for_all_loan (15), offering_fund (0), office_address (3), office_custom_field (0), office_hierarchy (0), office_holiday (0), original_loan_fee_schedule (1), original_loan_schedule (99), penalty (0), personnel_custom_field (0), personnel_hierarchy (0), personnel_movement (0), personnel_notes (0), ppi_likelihoods (0), ppi_survey (0), ppi_survey_instance (0), prd_checklist (0), prd_fee_frequency (0), prd_offering (19), prd_offering_fees (2), prd_offering_meeting (23), prd_offering_mix (0), prd_offering_question_group (28), product_offering_mandatory_savings (0), program (0), program_fund (0), question_choice_tags (0), question_choices (46), question_group (15), question_group_event_sources (18), question_group_instance (1), question_group_response (0), questions (13), recur_on_day (74), recurrence_detail (74), report_datasource (0), report_parameter (0), report_parameter_map (0), saving_schedule (80), savings_account (3), savings_activity_details (1), savings_offering (4), savings_offering_historical_interest_detail (0), savings_performance (3), savings_trxn_detail (1), sections (23), sections_questions (47), survey (0), survey_instance (0), survey_questions (0), survey_response (0), temp_id (0), variable_installment_details (2), waive_off_history (0)
