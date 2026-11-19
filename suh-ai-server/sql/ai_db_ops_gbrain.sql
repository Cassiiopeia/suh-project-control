-- gbrain 팀 브레인 준비 함수: 슈퍼유저 전용 작업 3개를 ai_db_admin 에게 좁게 위임
-- 대상 3개: 이벤트 트리거(RLS 자동), BYPASSRLS 부여·회수, 읽기 전용 권한
-- 슈퍼유저(gbrain)로 template1 과 기존 gbrain_* DB 에 1회 실행 (새 DB 는 template1 에서 복사)
-- 호출 조건: 호출자(session_user)가 대상 계정을 ADMIN 으로 관리 (= ai_db_admin 이 만든 계정)

CREATE SCHEMA IF NOT EXISTS ai_db_ops AUTHORIZATION gbrain;
REVOKE ALL ON SCHEMA ai_db_ops FROM PUBLIC;

-- 대상 계정 검증 (이름 규칙, 슈퍼유저 아님, 호출자가 ADMIN 관리)
CREATE OR REPLACE FUNCTION ai_db_ops.assert_managed_role(target_role text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
  IF target_role !~ '^[a-z][a-z0-9_]{2,40}$' THEN
    RAISE EXCEPTION 'invalid role name' USING ERRCODE = '42602';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target_role) THEN
    RAISE EXCEPTION 'role not found' USING ERRCODE = '42704';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target_role AND rolsuper) THEN
    RAISE EXCEPTION 'protected role' USING ERRCODE = '42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_auth_members m
    JOIN pg_roles target ON target.oid = m.roleid
    JOIN pg_roles caller ON caller.oid = m.member
    WHERE target.rolname = target_role AND caller.rolname = session_user AND m.admin_option
  ) THEN
    RAISE EXCEPTION 'role not managed by caller' USING ERRCODE = '42501';
  END IF;
END $$;

-- 이 DB 를 gbrain 브레인으로 준비: 확장 > RLS 함수·이벤트 트리거 > 쓰기 계정 BYPASSRLS
CREATE OR REPLACE FUNCTION ai_db_ops.prepare_gbrain_database(writer_role text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
  PERFORM ai_db_ops.assert_managed_role(writer_role);
  CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;
  CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public;
  CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA public;

  -- gbrain v35 와 같은 함수 (gbrain v211 이 search_path 변경 > 쓰기 계정 소유 필요)
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE p.proname = 'auto_enable_rls' AND n.nspname = 'public') THEN
    EXECUTE $fn$
      CREATE FUNCTION public.auto_enable_rls() RETURNS event_trigger AS $body$
      DECLARE obj record;
      BEGIN
        FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands()
                   WHERE object_type = 'table' AND schema_name = 'public' LOOP
          EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', obj.object_identity);
        END LOOP;
      END; $body$ LANGUAGE plpgsql
    $fn$;
  END IF;
  EXECUTE format('ALTER FUNCTION public.auto_enable_rls() OWNER TO %I', writer_role);

  -- 이벤트 트리거는 슈퍼유저 소유 (gbrain 은 있으면 건너뜀)
  IF NOT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'auto_rls_on_create_table') THEN
    CREATE EVENT TRIGGER auto_rls_on_create_table ON ddl_command_end
      WHEN TAG IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      EXECUTE FUNCTION public.auto_enable_rls();
  END IF;

  EXECUTE format('ALTER ROLE %I BYPASSRLS', writer_role);
END $$;

-- 읽기 전용 팀원: CONNECT·USAGE > 기존·이후 표 SELECT > BYPASSRLS (gbrain 표 RLS 켜짐, 정책 없음)
CREATE OR REPLACE FUNCTION ai_db_ops.grant_gbrain_reader(reader_role text, writer_role text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
  PERFORM ai_db_ops.assert_managed_role(reader_role);
  PERFORM ai_db_ops.assert_managed_role(writer_role);
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), reader_role);
  EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', reader_role);
  EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', reader_role);
  EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', reader_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON TABLES TO %I', writer_role, reader_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON SEQUENCES TO %I', writer_role, reader_role);
  EXECUTE format('ALTER ROLE %I BYPASSRLS', reader_role);
END $$;

-- 읽기 권한 회수 (grant 의 역순, BYPASSRLS 도 회수)
CREATE OR REPLACE FUNCTION ai_db_ops.revoke_gbrain_reader(reader_role text, writer_role text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
  PERFORM ai_db_ops.assert_managed_role(reader_role);
  PERFORM ai_db_ops.assert_managed_role(writer_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE SELECT ON TABLES FROM %I', writer_role, reader_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM %I', writer_role, reader_role);
  EXECUTE format('REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM %I', reader_role);
  EXECUTE format('REVOKE SELECT ON ALL SEQUENCES IN SCHEMA public FROM %I', reader_role);
  EXECUTE format('REVOKE USAGE ON SCHEMA public FROM %I', reader_role);
  EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM %I', current_database(), reader_role);
  EXECUTE format('ALTER ROLE %I NOBYPASSRLS', reader_role);
END $$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ai_db_ops FROM PUBLIC;
GRANT USAGE ON SCHEMA ai_db_ops TO ai_db_admin;
GRANT EXECUTE ON FUNCTION ai_db_ops.prepare_gbrain_database(text) TO ai_db_admin;
GRANT EXECUTE ON FUNCTION ai_db_ops.grant_gbrain_reader(text, text) TO ai_db_admin;
GRANT EXECUTE ON FUNCTION ai_db_ops.revoke_gbrain_reader(text, text) TO ai_db_admin;
