package me.suhsaechan.somansabusreservation.global.util;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Random;

public class CommonUtil {
	private final Random random = new Random();

	private int getRandomNumber(int min, int max) {
		if (min == max) {
			return min;
		}
		return random.nextInt(max - min + 1) + min;
	}

	/**
	 * 문자열 SHA-256 해시 계산
	 */
	public static String calculateSha256ByStr(String input) {
		try {
			MessageDigest digest = MessageDigest.getInstance("SHA-256");
			byte[] hashBytes = digest.digest(input.getBytes(StandardCharsets.UTF_8));
			StringBuilder sb = new StringBuilder();
			for (byte b : hashBytes) {
				sb.append(String.format("%02x", b));
			}
			return sb.toString();
		} catch (Exception e) {
			throw new RuntimeException("SHA-256 해시 계산 실패", e);
		}
	}

	/**
	 * 파일 SHA-256 해시값 계산
	 */
	public static String calculateFileHash(Path filePath) {
		try {
			MessageDigest digest = MessageDigest.getInstance("SHA-256");
			byte[] fileBytes = Files.readAllBytes(filePath);
			byte[] hashBytes = digest.digest(fileBytes);
			StringBuilder sb = new StringBuilder();
			for (byte b : hashBytes) {
				sb.append(String.format("%02x", b));
			}
			return sb.toString();
		} catch (Exception e) {
			throw new RuntimeException("파일 해시 계산 실패", e);
		}
	}


	/*
	null 또는 "null"/빈 문자열을 빈 문자열("")로 치환
	 */
	public static String nvl(Object str) {
		return nvl(String.valueOf(str), "");
	}

	public static String nvl(String str) {
		return nvl(str, "");
	}

	public static String nvl(Object str, String str1) {
		return nvl(String.valueOf(str), str1);
	}

	public static String nvl(String str, String str1) {
		if (null == str) {
			return str1;
		} else if ("null".equals(str) == true) {
			return str1;
		} else if ("".equals(str) == true) {
			return str1;
		}
		return str;
	}
}
