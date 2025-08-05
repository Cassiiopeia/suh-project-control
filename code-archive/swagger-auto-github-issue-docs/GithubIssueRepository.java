package me.suhsaechan.somansabusreservation.repository;

import java.util.Optional;
import java.util.UUID;
import me.suhsaechan.somansabusreservation.object.dao.GithubIssue;
import org.springframework.data.jpa.repository.JpaRepository;

public interface GithubIssueRepository extends JpaRepository<GithubIssue, UUID> {
  Optional<GithubIssue> findByIssueNumber(Integer issueNumber);
}
