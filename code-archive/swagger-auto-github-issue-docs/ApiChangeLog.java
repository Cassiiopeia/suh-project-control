package me.suhsaechan.somansabusreservation.global.docs;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import me.suhsaechan.somansabusreservation.object.constants.Author;

@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface ApiChangeLog {

  String date();

  Author author();

  String description();

  // 이슈번호 (기본값 -1 미지정, 양수값이면 이슈칼럼 링크추가)
  int issueNumber() default -1;
}
