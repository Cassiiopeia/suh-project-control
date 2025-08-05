package me.suhsaechan.somansabusreservation.repository;

import java.util.Optional;
import java.util.UUID;
import me.suhsaechan.somansabusreservation.object.constants.HashType;
import me.suhsaechan.somansabusreservation.object.dao.HashRegistry;
import org.springframework.data.jpa.repository.JpaRepository;

public interface HashRegistryRepository extends JpaRepository<HashRegistry, UUID> {
  Optional<HashRegistry> findByHashType(HashType hashType);
}
