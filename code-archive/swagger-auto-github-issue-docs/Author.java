package me.suhsaechan.somansabusreservation.object.constants;

// Swagger DOCS에서 @ApiChangeLog 어노테이션에 사용
public enum Author {
  SUHSAECHAN("서새찬");

  private final String displayName;

  Author(String displayName) {
    this.displayName = displayName;
  }

  public String getDisplayName() {
    return displayName;
  }
}
