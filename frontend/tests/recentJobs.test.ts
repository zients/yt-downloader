import {
  addRecentJob,
  hydrateRecentJobs,
  markRecentJobAutoDownloaded,
  RECENT_JOBS_LIMIT,
  updateRecentJobConversion,
  type RecentJob,
} from "../src/recentJobs";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

function assertEqual<T>(actual: T, expected: T, message: string) {
  if (actual !== expected) {
    throw new Error(
      `${message}: expected ${String(expected)}, got ${String(actual)}`,
    );
  }
}

const baseJobs: RecentJob[] = [
  { taskId: "task-1", createdAt: 1, updatedAt: 1 },
  { taskId: "task-2", createdAt: 2, updatedAt: 2 },
  { taskId: "task-3", createdAt: 3, updatedAt: 3 },
  { taskId: "task-4", createdAt: 4, updatedAt: 4 },
  { taskId: "task-5", createdAt: 5, updatedAt: 5 },
];

function testAddRecentJobPrependsAndTrims() {
  const jobs = addRecentJob(baseJobs, "task-6", 6);

  assertEqual(jobs.length, RECENT_JOBS_LIMIT, "keeps only the latest jobs");
  assertEqual(jobs[0]?.taskId, "task-6", "prepends newest submitted task");
  assertEqual(
    jobs[jobs.length - 1]?.taskId,
    "task-4",
    "drops the oldest task",
  );
}

function testAddRecentJobDeduplicatesTaskId() {
  const jobs = addRecentJob(baseJobs, "task-3", 10);

  assertEqual(
    jobs.length,
    RECENT_JOBS_LIMIT,
    "does not duplicate an existing task",
  );
  assertEqual(jobs[0]?.taskId, "task-3", "moves existing task to the top");
  assertEqual(jobs[0]?.createdAt, 3, "preserves original creation time");
  assertEqual(jobs[0]?.updatedAt, 10, "updates the changed time");
}

function testUpdateRecentJobConversionChangesOneCard() {
  const jobs = updateRecentJobConversion(baseJobs, "task-3", "conversion-3", 11);

  assertEqual(jobs.length, baseJobs.length, "keeps the same number of jobs");
  assertEqual(
    jobs[2]?.conversionId,
    "conversion-3",
    "stores conversion on the matching task",
  );
  assertEqual(jobs[2]?.updatedAt, 11, "updates the matching task timestamp");
  assertEqual(
    jobs[0]?.taskId,
    "task-1",
    "does not reorder cards on conversion creation",
  );
}

function testUpdateRecentJobConversionClearsStaleAutoDownloadMarker() {
  const jobs = updateRecentJobConversion(
    [
      {
        taskId: "task-1",
        conversionId: "old-conversion",
        autoDownloadedConversionId: "old-conversion",
        createdAt: 1,
        updatedAt: 1,
      },
    ],
    "task-1",
    "new-conversion",
    12,
  );

  assertEqual(
    jobs[0]?.autoDownloadedConversionId,
    undefined,
    "clears auto-download marker when a new conversion is created",
  );
}

function testMarkRecentJobAutoDownloadedStoresConversionId() {
  const jobs = markRecentJobAutoDownloaded(
    [{ taskId: "task-1", conversionId: "conversion-1", createdAt: 1, updatedAt: 1 }],
    "task-1",
    "conversion-1",
    13,
  );

  assertEqual(
    jobs[0]?.autoDownloadedConversionId,
    "conversion-1",
    "stores the auto-downloaded conversion id",
  );
  assertEqual(jobs[0]?.updatedAt, 13, "updates the matching task timestamp");
}

function testHydrateRecentJobsFiltersInvalidAndLimits() {
  const serialized = JSON.stringify([
    {
      taskId: "valid-1",
      conversionId: "conversion-1",
      autoDownloadedConversionId: "conversion-1",
      createdAt: 20,
      updatedAt: 21,
    },
    {
      taskId: "stale-marker",
      conversionId: "conversion-2",
      autoDownloadedConversionId: "other-conversion",
      createdAt: 19,
      updatedAt: 19,
    },
    { taskId: "", createdAt: 18, updatedAt: 18 },
    { taskId: "valid-2", conversionId: 12, createdAt: "bad", updatedAt: 18 },
    { taskId: "valid-3", createdAt: 17, updatedAt: 17 },
    { taskId: "valid-4", createdAt: 16, updatedAt: 16 },
    { taskId: "valid-5", createdAt: 15, updatedAt: 15 },
    { taskId: "valid-6", createdAt: 14, updatedAt: 14 },
  ]);

  const jobs = hydrateRecentJobs(serialized);

  assertEqual(jobs.length, RECENT_JOBS_LIMIT, "hydrates at most five jobs");
  assertEqual(jobs[0]?.taskId, "valid-1", "keeps first valid job");
  assertEqual(
    jobs[0]?.conversionId,
    "conversion-1",
    "keeps valid conversion id",
  );
  assertEqual(
    jobs[0]?.autoDownloadedConversionId,
    "conversion-1",
    "keeps matching auto-download marker",
  );
  assertEqual(
    jobs[1]?.autoDownloadedConversionId,
    undefined,
    "drops stale auto-download marker",
  );
  assertEqual(jobs[2]?.taskId, "valid-2", "recovers invalid timestamps");
  assertEqual(jobs[2]?.conversionId, undefined, "drops invalid conversion id");
  assert(jobs.every((job) => job.taskId !== ""), "filters empty task ids");
}

testAddRecentJobPrependsAndTrims();
testAddRecentJobDeduplicatesTaskId();
testUpdateRecentJobConversionChangesOneCard();
testUpdateRecentJobConversionClearsStaleAutoDownloadMarker();
testMarkRecentJobAutoDownloadedStoresConversionId();
testHydrateRecentJobsFiltersInvalidAndLimits();

console.log("recentJobs tests passed");
