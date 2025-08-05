package me.suhsaechan.somansabusreservation.global.docs;

import io.swagger.v3.oas.models.Operation;
import java.util.Set;
import java.util.TreeSet;
import lombok.RequiredArgsConstructor;
import org.springdoc.core.customizers.OperationCustomizer;
import org.springframework.core.annotation.MergedAnnotation;
import org.springframework.core.annotation.MergedAnnotations;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;

@Component
@RequiredArgsConstructor
public class CustomOperationCustomizer implements OperationCustomizer {

  private final GithubIssueService githubIssueService;

  @Override
  public Operation customize(Operation operation, HandlerMethod handlerMethod) {
    // @ApiChangeLogs 어노테이션 읽기
    MergedAnnotations annotations = MergedAnnotations.from(handlerMethod.getMethod(), MergedAnnotations.SearchStrategy.TYPE_HIERARCHY);
    MergedAnnotation<ApiChangeLogs> apiChangeLogsAnnotation = annotations.get(ApiChangeLogs.class);

    if (apiChangeLogsAnnotation.isPresent()) {
      ApiChangeLog[] apiChangeLogs = apiChangeLogsAnnotation.synthesize().value();

      // 이슈 번호를 TreeSet에 담아 정렬 및 중복 제거
      Set<Integer> issueNumbers = new TreeSet<>();
      for (ApiChangeLog log : apiChangeLogs) {
        if (log.issueNumber() > 0) {
          issueNumbers.add(log.issueNumber());
        }
      }

      StringBuilder tableBuilder = new StringBuilder();
      tableBuilder.append("\n\n**변경 관리 이력:**\n")
          .append("<table>\n")
          .append("<thead>\n")
          .append("<tr>")
          .append("<th>날짜</th>")
          .append("<th>작성자</th>")
          .append("<th>이슈번호</th>")
          .append("<th>이슈 제목</th>")
          .append("<th>변경 내용</th>")
          .append("</tr>\n")
          .append("</thead>\n")
          .append("<tbody>\n");

      for (ApiChangeLog log : apiChangeLogs) {
        String description = log.description()
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;");
        String issueNumberCell = "";
        String issueTitleCell = "";

        if (log.issueNumber() > 0) {
          // HTML 태그 이슈연결 : <a href="https://github.com/레포지토리/issues/번호">#번호</a>
          issueNumberCell = String.format("<a href=\"%s%d\" target=\"_blank\">#%d</a>",
              GithubIssueService.ISSUE_BASE_URL,
              log.issueNumber(),
              log.issueNumber());
          try {
            issueTitleCell = githubIssueService.getOrFetchIssue(log.issueNumber()).getCleanTitle();
          } catch (Exception e) {
            issueTitleCell = "ERROR";
          }
        }

        tableBuilder.append(String.format(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>\n",
            log.date(),
            log.author().getDisplayName(),
            issueNumberCell,
            issueTitleCell,
            description));
      }


      tableBuilder.append("</tbody>\n")
          .append("</table>\n");

      String originalDescription = operation.getDescription() != null ? operation.getDescription() : "";
      operation.setDescription(originalDescription + tableBuilder.toString());
    }
    return operation;
  }
}
