from typing import Optional
from typing import List
from typing_extensions import Self
from typing import Union

from dataclasses import field
from dataclasses import dataclass

from datetime import datetime as dt
from datetime import timezone

from fast_gmail.helpers import GoogleService
from fast_gmail.helpers import Labels
from fast_gmail.helpers import GmailLabel
from fast_gmail.helpers import LabelAction
from fast_gmail.helpers import DATE_FORMAT

from googleapiclient.errors import HttpError

import base64
import os


@dataclass
class MessagePartBody(object):
	size: int
	attachmentId: Optional[str] = None
	data: Optional[str] = None

@dataclass
class MessageHeader(object):
	name: str
	value: str

@dataclass
class Attachment(object):
	"""Represents an attachment associated with a Gmail message.
		Attributes:
			filename (str): Name of the attachment file.
			mimeType (str): MIME type of the attachment content.
			part_id (str): Internal identifier for the attachment within the message parts. Used for download with the Gmail API.
			google_service (GoogleService): Reference to the Google service object used for downloading the attachment.
			id (Optional[str], optional): ID of the attachment generated by Gmail after a message fetch (.get() method). Defaults to None.
			data (Optional[str], optional): Base64 encoded content of the attachment data. Defaults to None.
		Methods:
			download(): Downloads the attachment data from the Gmail API (if not already downloaded).
			save(filepath: Optional[str]=None, overwrite: bool=False): Saves the attachment data to a file.
    """
	filename: str
	mimeType: str
	part_id: str  # used to map with google attachments
	google_service: GoogleService
	id: Optional[str] = None   # google will generate new id(hash) each time the message is get with .get() method
	data: Optional[str] = None

	def __init__(
		self,
		filename: str,
		mimeType: str,
		part_id: str,
		google_service: GoogleService,
		id: Optional[str] = None,
		data: Optional[str] = None
	):
		self.filename = filename
		self.mimeType = mimeType
		self.google_service = google_service
		self.id = id
		self.data = data
		self.part_id = part_id

	def download(self)-> None:
		"""Downloads the attachment data from the Gmail API (if not already downloaded).
			Raises:
				TypeError: If the google_service.message_id attribute is missing.
				HttpError: An exception if there is an error fetching the attachment data from the Gmail API.
        """
		if not self.id:
			return None
		if self.data:
			return None
		if not self.google_service.message_id:
			raise TypeError("Attachment.google_service.message_id missing")
		try:
			res: Optional[MessagePartBody] = self.google_service.service.users().messages().attachments().get(
				userId = self.google_service.user_id,
				messageId = self.google_service.message_id,
				id = self.id
			).execute()
		except HttpError as e:
			raise e
		finally:
			self.google_service.service.close()
		if not res or "data" not in res:
			return None
		self.data = base64.urlsafe_b64decode(res["data"])
	
	def save(
		self,
		filepath: Optional[str]=None,
		overwrite: bool = False
	)-> None:
		"""Saves the attachment data to a file.
			Args:
				filepath (Optional[str], optional): Path to save the attachment. Defaults to the attachment filename.
				overwrite (bool, optional): Whether to overwrite an existing file. Defaults to False.
			Raises:
				FileExistsError: If the target file already exists and overwrite is False.
		"""
		
		if not filepath:
			filepath = self.filename
		if not self.data:
			self.download()
		if os.path.exists(filepath) and not overwrite:
			raise FileExistsError(
				f"""\
					{filepath} allready exists. \
					Call save(file_path, overwrite=True) \
					to rewrite the existing file\
				"""
			)
		with open(filepath, "wb") as f:
			f.write(self.data)

	def __str__(self):
		return self.filename

@dataclass
class MessagePart(object):
	"""Represents a single part of a Gmail message.
		A message part can be the main body content, an attachment, or a nested structure
		containing further parts.
		Attributes:
			mimeType (Optional[str]): MIME type of the message part content.
			headers (List[MessageHeader]): List of message headers associated with this part.
			parts (List[Self]): List of nested message parts (if any).
			partId (Optional[str]): Internal identifier for the part within the Gmail message.
			filename (Optional[str]): Filename associated with the part (if it's an attachment).
			body (Optional[MessagePartBody]): Information about the part's body content.
		Methods:
			_has_attachments(): Checks if the message part or its nested parts contain attachments.
			get_attachment_by_filename(filename: str) -> Union[Attachment, None]: Gets an attachment by its filename.
			get_attachment_by_part_id(id: str) -> Union[Attachment, None]: Gets an attachment by its internal part ID.
			attachments: Optional[List[Attachment]]: Property that returns a list of Attachment objects for all attachments within this part and its nested parts.
			get_header(key: str) -> Optional[MessageHeader]: Gets a message header by its name (key).
	"""
	mimeType: Optional[str]
	headers: List[MessageHeader] = field(default_factory=lambda : [])
	parts: List[Self] = field(default_factory=lambda : [])
	partId: Optional[str] = None
	filename: Optional[str] = None
	body: Optional[MessagePartBody] = None

	def __init__(self, google_service: GoogleService, **kwargs):
		self.google_service = google_service
		self.mimeType = kwargs.pop("mimeType", None)
		self.filename = kwargs.pop("filename", None)
		self.partId = kwargs.pop("partId", None)
		self.headers = [MessageHeader(**hdr) for hdr in kwargs.pop("headers", None)] if "headers" in kwargs else []
		self.body = MessagePartBody(**kwargs.pop("body", None)) if "body" in kwargs else None
		self.parts = [MessagePart(google_service=self.google_service, **part) for part in kwargs.pop("parts", None)] if "parts" in kwargs else []

	def _has_attachments(self)-> bool:
		"""Checks if the message part or its nested parts contain attachments."""
		if self.filename:
			return True
		if not self.parts:
			return False
		for part in self.parts:
			if part.filename:
				return True
		return False
	
	def get_attachment_by_filename(self, filename: str)-> Union[Attachment, None]:
		"""Gets an attachment by its filename."""
		if not filename or len(filename) == 0:
			return None
		if not self._has_attachments():
			return None
		for attachment in self.attachments:
			if attachment.filename == filename:
				return attachment
		return None
	
	def get_attachment_by_part_id(self, id: str)-> Union[Attachment, None]:
		"""Gets an attachment by its internal part ID."""
		if not id or len(id) == 0:
			return None
		if not self._has_attachments():
			return None
		for attachment in self.attachments:
			if attachment.part_id == id:
				return attachment
		return None

	@property
	def attachments(self)-> Optional[List[Attachment]]:
		"""Property that returns a list of Attachment objects for all attachments within this part and its nested parts."""
		if not self._has_attachments():
			return []
		attachments = []
		for part in self.parts:
			if part.filename:
				if part.body.attachmentId:
					attachments.append(Attachment(
						filename=part.filename.replace("/", "_"),
						mimeType=part.mimeType if part.mimeType else "",
						id = part.body.attachmentId,
						google_service=self.google_service,
						part_id = part.partId
					))
				else:
					attachments.append(Attachment(
						filename=part.filename.replace("/", "_"),
						mimeType=part.mimeType if part.mimeType else "",
						data = part.body.data,
						google_service=self.google_service,
						part_id = part.partId
					))
		return attachments

	def get_header(self, key: str)-> Optional[MessageHeader]:
		"""Gets a message header by its name (key)."""
		if not self.headers or len(self.headers) == 0:
			return None
		if not key:
			return self.headers
		for header in self.headers:
			if key == header.name:
				return header
		return None

@dataclass
class Message(object):
	"""Represents a single email message within a Gmail account.
		This class provides access to various message properties and functionalities,
		including content retrieval, attachment handling, label management, and
		common actions like marking as read/unread or starring.

		Attributes:
			id (str): Unique identifier for the message.
			snippet (str): Shortened summary of the message content.
			threadId (str): Thread ID that groups related messages together.
			historyId (str): Unique identifier for a specific message history change.
			sizeEstimate (int): Approximate size of the message in bytes.
			internalDate (str): Internal timestamp representing when the message was created.
			payload (MessagePart): Object of type `MessagePart` containing the parsed content
								of the message body and attachments.
			raw (Optional[str]): Optional property containing the raw email data (if available).
			labelIds (List[Labels]): List of label IDs associated with the message.
			labels (Optional[List[GmailLabel]]): List of `GmailLabel` objects representing the
												message's labels (fetched on demand).
		Properties:
			message_headers (Optional[List[MessageHeader]]): List of `MessageHeader` objects
															from the message's payload (if available).
			body (str): Returns the message body content (combines plain text and HTML if both exist).
			html (str): Returns the HTML content of the message body (if available).
			plain (str): Returns the plain text content of the message body (if available).
			alternative (str): Returns the text content of the most appropriate alternative part
							(if message uses multipart/alternative).
			recipient (str): Extracts the recipient's email address from the "To" header (if available).
			message_id (str): Extracts the message ID from the message headers (if available).
			subject (str): Extracts the subject line from the message headers (if available).
			sender (str): Extracts the sender's email address from the "From" header (if available).
			has_attachments (bool): Checks if the message or its nested parts contain attachments.
			attachments (Optional[List[Attachment]]): Returns a list of `Attachment` objects for
													all attachments within the message.
			is_unread (bool): Indicates whether the message has the unread label.
			is_starred (bool): Indicates whether the message has the starred label.
			is_important (bool): Indicates whether the message has the important label.
			is_spam (bool): Indicates whether the message has the spam label.
			is_draft (bool): Indicates whether the message has the draft label.
			is_trash (bool): Indicates whether the message has the trash label.
			created_date (datetime): Converts the `internalDate` to a datetime object representing
									the message creation time.
			date (Optional[datetime]): Parses the "Received" or "Date" header to get the message
									delivery date (if available).
			date_string (Optional[str]): Formats the delivery date according to a specified format string
										(defaults to "%a, %d %b %Y %H:%M:%S %z").
		Methods:
			mark_as_read(self) -> Self: Toggles the unread flag for the message.
			mark_as_unread(self) -> Self: Toggles the unread flag for the message.
			toogle_read_unread(self) -> Self: Shortcut to toggle the unread flag based on the current state.
			mark_spam(self) -> Self: Toggles the spam label for the message.
			mark_not_spam(self) -> Self: Toggles the spam label for the message.
			toggle_spam(self) -> Self: Shortcut to toggle the spam label based on the current state.
			move_to_trash(self) -> Self: Toggles the trash label for the message.
			move_from_trash(self) -> Self: Toggles the trash label for the message.
			toggle_trash(self) -> Self: Shortcut to toggle the trash label based on the current state.
			mark_important(self) -> Self: Toggles the important label for the message.
			mark_not_important(self) -> Self: Toggles the important label for the message.
			toggle_important(self) -> Self: Shortcut to toggle the important label based on the current state.
			mark_starred(self) -> Self: Toggles the starred label for the message.
			mark_not_starred(self) -> Self: Toggles the starred label for the message.
			toggle_starred(self) -> Self: Shortcut to toggle the starred label based on the current state.
			get_attachment(self, filename: Optional[str] = None, id: Optional[str] = None) -> Union[Attachment, None]: Retrieves an attachment by filename or internal part ID.
			get_labels(self) -> Optional[List[GmailLabel]]: Fetches and returns a list of `GmailLabel` objects for all labels associated with the message.
			add_label(self, label: Union[Labels, str]) -> bool: Adds a label to the message.
			add_labels(self, labels: Union[List[Labels], List[str]]) -> bool: Adds labels to the message.
			remove_label(self, label: Union[Labels, str]) -> bool: Removes a label from the message.
			remove_labels(self, labels: Union[List[Labels], List[str]]) -> bool: Removes labels from the message.
			modify_labels(self, labels_to_add: Optional[Union[List[Labels], List[str]]], labels_to_remove: Optional[Union[List[Labels], List[str]]]) -> bool: Updates message labels by adding and/or removing labels.
    """
	id: str
	snippet: str
	threadId: str
	historyId: str
	sizeEstimate: int
	internalDate: str
	payload: MessagePart
	raw: Optional[str] = None
	labelIds: List[Labels] = field(default_factory=lambda : [])
	labels: Optional[List[GmailLabel]] = None

	def __init__(self, google_service: GoogleService, **kwargs):
		self.id = kwargs.pop("id", None)
		self.threadId = kwargs.pop("threadId", None)
		self.snippet = kwargs.pop("snippet", None)
		self.historyId = kwargs.pop("historyId", None)
		self.internalDate = kwargs.pop("internalDate", None)
		self.sizeEstimate = kwargs.pop("sizeEstimate", None)
		self.raw = kwargs.pop("raw", None)
		self.labelIds = kwargs.pop("labelIds", None)
		self.google_service = google_service
		if "payload" in kwargs:
			self.payload = MessagePart(google_service=self.google_service, **kwargs["payload"])

	def __str__(self):
		return self.subject if self.subject else (self.snippet if self.snippet else "")

	@property
	def message_headers(self)-> Optional[List[MessageHeader]]:
		if not self.payload:
			return None
		if not self.payload.headers:
			return None
		return self.payload.headers

	def _extract_content(self, part: MessagePart, result: dict)-> None:
		# TODO: load cid: images into content
		if part.mimeType not in ["text/plain", "text/html"]:
			for sub_part in part.parts:
				self._extract_content(sub_part, result)
		if not part.mimeType in result:
			result[part.mimeType] = []
		if not part.body:
			return
		if not part.body.data:
			return
		result[part.mimeType].append(
			base64.urlsafe_b64decode(part.body.data).decode("utf-8")
		)

	def _content(self)-> Optional[dict]:
		if not self.payload:
			return None
		result = {}
		if not self.payload.parts:
			if self.payload.mimeType in ["text/plain", "text/html"] and self.payload.body:
				if self.payload.body.data:
					if not self.payload.mimeType in result:
						result[self.payload.mimeType] = []
					result[self.payload.mimeType].append(
						base64.urlsafe_b64decode(self.payload.body.data).decode("utf-8")
					)
					return result
			return {
				"multipart/alternative": base64.urlsafe_b64decode(
					self.payload.body.data
				).decode("utf-8")} if self.payload.body else None
		for part in self.payload.parts:
			self._extract_content(part, result)
		return result
	
	@property
	def body(self)-> str:
		return self.html if self.html and len(self.html) > 0 else self.plain

	@property
	def html(self)-> str:
		content = self._content()
		if not content:
			return ""
		if "text/html" not in content:
			return ""
		return " ".join(content["text/html"])
		
	@property
	def plain(self)-> str:
		content = self._content()
		if not content:
			return ""
		if "text/plain" not in content:
			return ""
		return " ".join(content["text/plain"])

	@property
	def alternative(self)-> str:
		content = self._content()
		if not content:
			return ""
		if "multipart/alternative" not in content:
			return ""
		return " ".join(content["multipart/alternative"])
	
	@property
	def recipient(self)-> Union[str, None]:
		if not self.message_headers:
			return None
		for header in self.message_headers:
			if header.name == "To":
				return header.value
		return None

	@property
	def message_id(self)-> Union[str, None]:
		if not self.message_headers:
			return None
		for header in self.message_headers:
			if header.name.casefold() == "message-id":
				return header.value
		return None

	@property
	def subject(self)-> Union[str, None]:
		if not self.message_headers:
			return None
		for header in self.message_headers:
			if header.name == "Subject":
				return header.value
		return None

	@property
	def sender(self)-> Union[str, None]:
		"""Returns only the name or email address of the sender"""
		sender = self.sender_header
		if not sender:
			return None
		if "\"" in sender:
			sender = sender.split("\"")[1]
		else:
			if "<" in sender:
				sender = sender.split("<")[1].replace(">", "")
		return sender
	
	@property
	def sender_header(self)-> Union[str, None]:
		"""Returns the sender message Header"""
		if not self.message_headers:
			return None
		for header in self.message_headers:
			if header.name == "From":
				return header.value
		return None
	
	@property
	def has_attachments(self)-> bool:
		if not self.payload: return False
		return self.payload._has_attachments()

	@property
	def attachments(self)-> Optional[List[Attachment]]:
		return self.payload.attachments

	@property
	def is_unread(self)-> bool:
		if not self.labelIds:
			return False
		if Labels.UNREAD.value in [x for x in self.labelIds]:
			return True
		return False
	
	@property
	def is_starred(self)-> bool:
		if not self.labelIds:
			return False
		if Labels.STARRED.value in [x for x in self.labelIds]:
			return True
		return False
	
	@property
	def is_important(self)-> bool:
		if not self.labelIds:
			return False
		if Labels.IMPORTANT.value in [x for x in self.labelIds]:
			return True
		return False

	@property
	def is_spam(self)-> bool:
		if not self.labelIds:
			return False
		if Labels.SPAM.value in [x for x in self.labelIds]:
			return True
		return False

	@property
	def is_draft(self)-> bool:
		if not self.labelIds:
			return False
		if Labels.DRAFT.value in [x for x in self.labelIds]:
			return True
		return False

	@property
	def is_trash(self)-> bool:
		if not self.labelIds:
			return False
		if Labels.TRASH.value in [x for x in self.labelIds]:
			return True
		return False

	@property
	def created_date(self)-> dt:
		"""internalDate is the time when messages was created"""
		seconds_from_epoch: int
		try:
			seconds_from_epoch = int(self.internalDate)/1000
		except ValueError:
			raise ValueError(f"{self.internalDate=} can't be cast to int")
		return dt.fromtimestamp(seconds_from_epoch)

	@property
	def date(self)-> Optional[dt]:
		"""returns the date when message was delivered"""
		received = self.payload.get_header("Received")
		split_to_extract: bool = True
		if not received:
			split_to_extract = False
			received = self.payload.get_header("Date")
		if not received:
			return None
		
		date_part: str = received.value
		if split_to_extract:
			_, date_part = received.value.split("; ")
			if not date_part:
				return None
			if "(" in date_part:
				date_part, _ = date_part.split("(")
				if not date_part:
					return None
			date_part = date_part.strip()

		return dt.strptime(date_part, f"%a, %d %b %Y %H:%M:%S %z")
		
	def date_string(self, format: Optional[str] = DATE_FORMAT)-> Optional[str]:
		"""returns fomated delivered date, cheatsheet: https://strftime.org/"""
		if not self.date:
			return None
		date = self.date.astimezone() # set to locale timezone
		if date.year == dt.now(timezone.utc).astimezone().year:
			format = format.replace(", %Y", "")
		return date.strftime(format)

	@property
	def mark_as_read(self)-> Self:
		self.remove_label(Labels.UNREAD.value)
		return self
	
	@property
	def mark_as_unread(self)-> Self:
		self.add_label(Labels.UNREAD.value)
		return self

	@property
	def toggle_read_unread(self)-> Self:
		if self.is_unread:
			self.remove_label(Labels.UNREAD.value)
		else:
			self.add_label(Labels.UNREAD.value)
		return self

	@property
	def mark_spam(self)-> Self:
		self._edit_labels(
			action=LabelAction.TOGGLE,
			add=[Labels.SPAM.value],
			remove=[
				Labels.TRASH.value,
				Labels.INBOX.value,
				Labels.STARRED.value,
				Labels.IMPORTANT.value,
			]
		)
		return self
	
	@property
	def mark_not_spam(self)-> Self:
		self._edit_labels(
			action=LabelAction.TOGGLE,
			add=[Labels.INBOX.value],
			remove=[Labels.SPAM.value]
		)
		return self

	@property
	def toggle_spam(self)-> Self:
		if self.is_spam:
			self.mark_not_spam
		else:
			self.mark_spam
		return self

	@property
	def move_to_trash(self)-> Self:
		self._edit_labels(
			action=LabelAction.TOGGLE,
			add=[Labels.TRASH.value],
			remove=[
				Labels.INBOX.value,
				Labels.STARRED.value,
				Labels.IMPORTANT.value,
			]
		)
		return self

	@property
	def move_from_trash(self)-> Self:
		self._edit_labels(
			action=LabelAction.TOGGLE,
			add=[Labels.INBOX.value],
			remove=[Labels.TRASH.value]
		)
		return self

	@property
	def toggle_trash(self)-> Self:
		if self.is_trash:
			self.move_from_trash
		else:
			self.move_to_trash
		return self

	@property
	def mark_important(self)-> Self:
		self.add_label(Labels.IMPORTANT.value)
		return self
	
	@property
	def mark_not_important(self)-> Self:
		self.remove_label(Labels.IMPORTANT.value)
		return self

	@property
	def toggle_important(self)-> Self:
		if self.is_important:
			return self.mark_not_important
		return self.mark_important

	@property
	def mark_starred(self)-> Self:
		self.add_label(Labels.STARRED.value)
		return self
	
	@property
	def mark_not_starred(self)-> Self:
		self.remove_label(Labels.STARRED.value)
		return self

	@property
	def toggle_starred(self)-> Self:
		if self.is_starred:
			return self.mark_not_starred
		return self.mark_starred

	def get_attachment(
		self,
		filename: Optional[str] = None,
		id: Optional[str] = None
	)-> Union[Attachment, None]:
		"""Retrieves an attachment by filename or internal part ID."""
		if not self.has_attachments:
			return None
		if filename:
			return self.payload.get_attachment_by_filename(filename)
		return self.payload.get_attachment_by_part_id(id)
	
	@property
	def get_labels(self)-> Optional[List[GmailLabel]]:
		"""gets all labels for this message"""
		if not self.labels:
			self.labels = []
		batch = self.google_service.service.new_batch_http_request()
		def get_label_response(request_id, response, exception):
			if exception is not None:
				raise exception
			self.labels.append(GmailLabel(**response))
			return
		for label_id in self.labelIds:
			batch.add(
				self.google_service.service.users().labels().get(
					userId = self.google_service.user_id,
					id = label_id
				),
				callback=get_label_response
			)
		batch.execute()
		return self.labels

	def add_label(self, label: Union[Labels, str])-> bool:
		return self._edit_labels(action=LabelAction.ADD, add=[label])
	
	def add_labels(self, labels: Union[List[Labels], List[str]])-> bool:
		return self._edit_labels(action=LabelAction.ADD, add=labels)
	
	def remove_label(self, label: Union[Labels, str])-> bool:
		return self._edit_labels(action=LabelAction.REMOVE, remove=[label])
	
	def remove_labels(self, labels: Union[List[Labels], List[str]])-> bool:
		return self._edit_labels(action = LabelAction.REMOVE, remove=labels)
	
	def modify_labels(
		self,
		labels_to_add: Optional[Union[List[Labels], List[str]]],
		labels_to_remove: Optional[Union[List[Labels], List[str]]]
	)-> bool:
		return self._edit_labels(
			action = LabelAction.TOGGLE,
			add = labels_to_add,
			remove = labels_to_remove
		)

	def _edit_labels(
		self,
		action: LabelAction,
		add: Optional[List[Labels]]=[],
		remove: Optional[List[Labels]]=[]
	)-> bool:
		
		payload = {}
		match action:
			case LabelAction.REMOVE:
				payload["removeLabelIds"] = [x for x in remove]
			case LabelAction.ADD:
				payload["addLabelIds"] = [x for x in add]
			case LabelAction.TOGGLE:
				payload["removeLabelIds"] = [x for x in remove]
				payload["addLabelIds"] = [x for x in add]
			case _:
				return False
		try:
			self.google_service.service.users().messages().modify(
				userId=self.google_service.user_id,
				id=self.id,
				body=payload
			).execute()
			match action:
				case LabelAction.ADD:
					for label in add:
						if label not in self.labelIds:
							self.labelIds.append(label)
				case LabelAction.REMOVE:
					for label in remove:
						if label in self.labelIds:
							self.labelIds.remove(label)
				case LabelAction.TOGGLE:
					for label in add:
						if label not in self.labelIds:
							self.labelIds.append(label)
					for label in remove:
						if label in self.labelIds:
							self.labelIds.remove(label)
				case _:
					return False
			return True
		except HttpError as e:
			raise e
		finally:
			self.google_service.service.close()


